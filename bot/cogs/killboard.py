"""Phase 6 — Killboard #champ-de-bataille."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import discord
from discord.ext import commands
from sqlalchemy import select

from bot.config import settings
from bot.database.crud import get_member_by_discord_id
from bot.database.engine import session_scope
from bot.database.models import KillEvent, Member, utcnow
from bot.services.albion_api import AlbionAPIClient, AlbionAPIError
from bot.utils.embeds import info_embed
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)


def _slot_name(item: dict[str, Any] | None) -> str:
    if not item:
        return "—"
    return item.get("Type") or item.get("TypeName") or "—"


def _equipment_lines(loadout: dict[str, Any] | None) -> str:
    if not loadout:
        return "inconnu"
    return (
        f"• Arme : {_slot_name(loadout.get('MainHand'))}\n"
        f"• Armure : {_slot_name(loadout.get('Armor'))}\n"
        f"• Casque : {_slot_name(loadout.get('Head'))}\n"
        f"• Bottes : {_slot_name(loadout.get('Shoes'))}"
    )


class Killboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = AlbionAPIClient()

    async def cog_unload(self) -> None:
        await self.api.close()

    async def sync_kills(self) -> int:
        try:
            events = await self.api.get_recent_events(limit=40)
        except AlbionAPIError:
            LOGGER.exception("Killboard API")
            return 0
        posted = 0
        async with session_scope() as session:
            members = list((await session.execute(select(Member))).scalars().all())
        names = {(m.albion_name or "").lower(): m for m in members if m.albion_name}

        for event in events:
            event_id = int(event.get("EventId") or 0)
            if not event_id:
                continue
            async with session_scope() as session:
                exists = await session.scalar(select(KillEvent.id).where(KillEvent.albion_event_id == event_id))
                if exists:
                    continue
            killer = event.get("Killer") or {}
            victim = event.get("Victim") or {}
            killer_name = killer.get("Name") or "?"
            victim_name = victim.get("Name") or "?"
            member = names.get(killer_name.lower())
            kind = "kill"
            if member is None:
                member = names.get(victim_name.lower())
                kind = "death"
            if member is None:
                continue
            occurred = event.get("TimeStamp") or utcnow().isoformat()
            try:
                when = datetime.fromisoformat(str(occurred).replace("Z", "+00:00"))
            except ValueError:
                when = utcnow()
            equipment = (killer if kind == "kill" else victim).get("Equipment") or {}
            async with session_scope() as session:
                session.add(
                    KillEvent(
                        albion_event_id=event_id,
                        event_type=kind,
                        member_id=member.id,
                        member_name=member.albion_name or member.discord_name,
                        opponent_name=victim_name if kind == "kill" else killer_name,
                        opponent_guild=((victim if kind == "kill" else killer).get("GuildName")),
                        fame=int(event.get("TotalVictimKillFame") or 0),
                        zone_name=(event.get("Location") or event.get("KillArea")),
                        occurred_at=when,
                        equipment=equipment if isinstance(equipment, dict) else {},
                        raw_payload=event if isinstance(event, dict) else {},
                    )
                )
            for guild in self.bot.guilds:
                channel = find_channel(guild, "battlefield")
                if channel is None:
                    continue
                if kind == "kill":
                    embed = info_embed(
                        f"⚔️ KILL — {killer_name} a tué {victim_name}",
                        f"💀 Cible : **{victim_name}** (guilde : {victim.get('GuildName') or '—'})\n"
                        f"🏆 Fame : {int(event.get('TotalVictimKillFame') or 0):,}\n"
                        f"🗺️ Zone : {event.get('Location') or '—'}\n\n"
                        f"🛡️ Équipement :\n{_equipment_lines(equipment)}",
                    )
                    embed.color = discord.Color.green()
                else:
                    embed = info_embed(
                        f"💀 MORT — {victim_name} est tombé",
                        f"⚔️ Tué par : **{killer_name}** (guilde : {killer.get('GuildName') or '—'})\n"
                        f"💸 Fame : {int(event.get('TotalVictimKillFame') or 0):,}\n"
                        f"🗺️ Zone : {event.get('Location') or '—'}\n\n"
                        f"🛡️ Équipement à la mort :\n{_equipment_lines(equipment)}",
                    )
                    embed.color = discord.Color.red()
                await channel.send(embed=embed)
                posted += 1
        return posted


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Killboard(bot))
