"""Phase 6 — Killboard #champ-de-bataille.

Sync fiable : poll des kills/morts de CHAQUE membre (endpoints /players/{id}/kills
et /deaths) au lieu du flux global /events (qui ne couvre que les derniers
évènements du serveur entier et ratait la plupart des kills/morts de la guilde).

Zone : l'API gameinfo renvoie ``Location: null`` pour les kills — on affiche le
type de zone (KillArea) habillé en rouge/noir/orange (léthal) quand c'est possible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import discord
from discord.ext import commands
from sqlalchemy import select

from bot.database.engine import session_scope
from bot.database.models import KillEvent, Member, utcnow
from bot.services.albion_api import AlbionAPIClient, AlbionAPIError
from bot.services.item_lookup import item_label
from bot.utils.equipment import character_render_url, item_icon_url, zone_line
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)

# Nombre de kills/morts récents récupérés par membre à chaque passe (5 min).
PER_MEMBER_LIMIT = 10
# Concurrence max des appels API.
API_CONCURRENCY = 5
# On ne poste que les évènements de moins de 24h (les plus anciens sont juste
# enregistrés, pour éviter un flood au premier lancement ou après une panne).
POST_WINDOW_HOURS = 24

EQUIPMENT_SLOTS = (
    ("Arme", "MainHand"),
    ("Secondaire", "OffHand"),
    ("Casque", "Head"),
    ("Armure", "Armor"),
    ("Bottes", "Shoes"),
    ("Cape", "Cape"),
    ("Monture", "Mount"),
)


def _event_id(event: dict[str, Any]) -> int:
    return int(event.get("EventId") or 0)


def _parse_timestamp(event: dict[str, Any]) -> datetime:
    raw = event.get("TimeStamp")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return utcnow()


class Killboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = AlbionAPIClient()

    async def cog_unload(self) -> None:
        await self.api.close()

    async def _load_members(self) -> list[Member]:
        async with session_scope() as session:
            return list((await session.execute(select(Member))).scalars().all())

    async def _resolve_player_id(self, name: str) -> str | None:
        """Résout le pseudo Albion → player id (pour les membres sans id stocké)."""

        try:
            search = await self.api.search_players(name)
        except AlbionAPIError:
            return None
        players = (search.get("players") if isinstance(search, dict) else None) or []
        if players and isinstance(players[0], dict):
            pid = players[0].get("Id")
            if pid:
                return str(pid)
        return None

    async def _poll_member(self, member: Member) -> tuple[list[tuple[dict[str, Any], Member]], list[tuple[dict[str, Any], Member]]]:
        """Récupère les kills/morts récents d'un membre (sans cache)."""

        pid = member.albion_player_id
        if not pid:
            return [], []
        kills: list[dict[str, Any]] = []
        deaths: list[dict[str, Any]] = []
        try:
            kills = await self.api.get_player_kills_fresh(pid, limit=PER_MEMBER_LIMIT) or []
        except AlbionAPIError:
            LOGGER.debug("Killboard: kills indisponibles pour %s", member.albion_name or pid)
        try:
            deaths = await self.api.get_player_deaths_fresh(pid, limit=PER_MEMBER_LIMIT) or []
        except AlbionAPIError:
            LOGGER.debug("Killboard: morts indisponibles pour %s", member.albion_name or pid)
        return (
            [(ev, member) for ev in kills if isinstance(ev, dict)],
            [(ev, member) for ev in deaths if isinstance(ev, dict)],
        )

    async def _equipment_lines(self, loadout: dict[str, Any] | None) -> str:
        if not isinstance(loadout, dict):
            return "*équipement inconnu*"
        lines: list[str] = []
        for label, key in EQUIPMENT_SLOTS:
            item = loadout.get(key)
            if not isinstance(item, dict):
                continue
            typ = item.get("Type") or item.get("TypeName")
            if not typ:
                continue
            lines.append(f"• {label} : {await item_label(typ)}")
        return "\n".join(lines) if lines else "*équipement inconnu*"

    async def _post_event(self, event: dict[str, Any], member: Member, kind: str) -> int:
        """Enregistre en base puis poste l'embed killboard. Retourne le nb posté."""

        event_id = _event_id(event)
        killer = event.get("Killer") if isinstance(event.get("Killer"), dict) else {}
        victim = event.get("Victim") if isinstance(event.get("Victim"), dict) else {}
        killer_name = killer.get("Name") or "?"
        victim_name = victim.get("Name") or "?"
        fame = int(event.get("TotalVictimKillFame") or 0)
        when = _parse_timestamp(event)

        # Ce qui tombe / est perdu = TOUJOURS l'équipement de la victime.
        victim_equipment = victim.get("Equipment") if isinstance(victim.get("Equipment"), dict) else {}

        member_name = member.albion_name or member.discord_name
        opponent_name = victim_name if kind == "kill" else killer_name
        opponent_guild = (victim if kind == "kill" else killer).get("GuildName")
        zone_name = (event.get("Location") or event.get("KillArea") or event.get("Category") or "")[:160] or None

        async with session_scope() as session:
            session.add(
                KillEvent(
                    albion_event_id=event_id,
                    event_type=kind,
                    member_id=member.id,
                    member_name=member_name,
                    opponent_name=opponent_name,
                    opponent_guild=opponent_guild,
                    fame=fame,
                    zone_name=zone_name,
                    occurred_at=when,
                    equipment=victim_equipment,
                    raw_payload=event if isinstance(event, dict) else {},
                )
            )

        # Un évènement trop ancien est enregistré sans être posté (anti-flood).
        if when < utcnow() - timedelta(hours=POST_WINDOW_HOURS):
            LOGGER.info("Killboard: évènement %s trop ancien, enregistré sans post", event_id)
            return 0

        zone = zone_line(event)
        fame_fmt = f"{fame:,}".replace(",", " ")
        equipment_lines = await self._equipment_lines(victim_equipment)

        if kind == "kill":
            embed = discord.Embed(
                title=f"⚔️ KILL — {killer_name} a éliminé {victim_name}",
                description=(
                    f"💀 Cible : **{victim_name}** (guilde : {victim.get('GuildName') or '—'})\n"
                    f"🏆 Fame : {fame_fmt}\n"
                    f"{zone}\n\n"
                    f"🛡️ Équipement de la cible :\n{equipment_lines}"
                ),
                color=discord.Color.green(),
            )
        else:
            embed = discord.Embed(
                title=f"💀 MORT — {victim_name} est tombé",
                description=(
                    f"⚔️ Tué par : **{killer_name}** (guilde : {killer.get('GuildName') or '—'})\n"
                    f"💸 Fame perdue : {fame_fmt}\n"
                    f"{zone}\n\n"
                    f"🛡️ Équipement perdu :\n{equipment_lines}"
                ),
                color=discord.Color.red(),
            )

        weapon = victim_equipment.get("MainHand")
        icon = item_icon_url(weapon.get("Type") if isinstance(weapon, dict) else None)
        if icon:
            embed.set_thumbnail(url=icon)
        portrait = character_render_url(victim_equipment)
        if portrait:
            embed.set_image(url=portrait)
        embed.timestamp = when
        embed.set_footer(text="Albion PPCF • Fort Sterling · killboard")

        posted = 0
        for guild in self.bot.guilds:
            channel = find_channel(guild, "battlefield")
            if channel is None:
                continue
            try:
                message = await channel.send(embed=embed)
            except discord.HTTPException:
                LOGGER.exception("Killboard: envoi impossible dans %s", guild.name)
                continue
            posted += 1
            async with session_scope() as session:
                row = await session.scalar(select(KillEvent).where(KillEvent.albion_event_id == event_id))
                if row is not None and row.posted_message_id is None:
                    row.posted_message_id = message.id
        if not posted:
            LOGGER.warning("Killboard: aucun salon #champ-de-bataille trouvé pour l'évènement %s", event_id)
        return posted

    async def _existing_event_ids(self, event_ids: list[int]) -> set[int]:
        """Ids déjà en base, par paquets (limite de paramètres SQLite)."""

        existing: set[int] = set()
        for i in range(0, len(event_ids), 500):
            chunk = event_ids[i : i + 500]
            async with session_scope() as session:
                rows = await session.execute(
                    select(KillEvent.albion_event_id).where(KillEvent.albion_event_id.in_(chunk))
                )
                existing.update(rows.scalars().all())
        return existing

    async def sync_kills(self) -> int:
        """Poll fiable des kills/morts de la guilde et poste les nouveaux."""

        members = await self._load_members()
        to_poll = [m for m in members if (m.albion_player_id or m.albion_name) and not m.left_at]
        semaphore = asyncio.Semaphore(API_CONCURRENCY)

        async def resolve_and_poll(
            member: Member,
        ) -> tuple[list[tuple[dict[str, Any], Member]], list[tuple[dict[str, Any], Member]]]:
            # Résout le pseudo → player id (une seule fois, mis en cache ensuite en base).
            if not member.albion_player_id and member.albion_name:
                try:
                    async with semaphore:
                        pid = await self._resolve_player_id(member.albion_name)
                except Exception:
                    LOGGER.exception("Killboard: résolution pseudo échouée pour %s", member.albion_name)
                    pid = None
                if pid:
                    async with session_scope() as session:
                        db = await session.get(Member, member.id)
                        if db is not None:
                            db.albion_player_id = pid
                    member.albion_player_id = pid
                else:
                    LOGGER.debug("Killboard: pseudo introuvable pour %s", member.albion_name)
            if not member.albion_player_id:
                return [], []
            async with semaphore:
                try:
                    return await self._poll_member(member)
                except Exception:
                    LOGGER.exception("Killboard: poll échoué pour %s", member.albion_name or member.id)
                    return [], []

        tasks = [asyncio.create_task(resolve_and_poll(m)) for m in to_poll]
        kill_events: list[tuple[dict[str, Any], Member]] = []
        death_events: list[tuple[dict[str, Any], Member]] = []
        if tasks:
            try:
                results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=150)
            except asyncio.TimeoutError:
                LOGGER.warning("Killboard: poll des membres interrompu (timeout)")
                results = []
            for result in results:
                if isinstance(result, BaseException):
                    continue
                kills, deaths = result
                kill_events.extend(kills)
                death_events.extend(deaths)

        # Dédoublonnage par EventId (un kill interne apparaît chez le tueur ET la victime).
        candidates: dict[int, tuple[dict[str, Any], Member, str]] = {}
        for ev, member in kill_events:
            eid = _event_id(ev)
            if eid:
                candidates.setdefault(eid, (ev, member, "kill"))
        for ev, member in death_events:
            eid = _event_id(ev)
            if eid:
                candidates.setdefault(eid, (ev, member, "death"))

        if not candidates:
            return 0

        existing_ids = await self._existing_event_ids(list(candidates))

        posted = 0
        for eid, (event, member, kind) in candidates.items():
            if eid in existing_ids:
                continue
            try:
                posted += await self._post_event(event, member, kind)
            except Exception:
                LOGGER.exception("Killboard: échec évènement %s", eid)
        return posted


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Killboard(bot))
