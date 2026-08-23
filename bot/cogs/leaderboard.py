"""Phase 7 — Classements ordres / fame / dons."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.database.engine import session_scope
from bot.database.models import ContributionScore, Member
from bot.services.albion_api import AlbionAPIClient, AlbionAPIError
from bot.utils.embeds import error_embed, format_silver, info_embed
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)
MEDALS = ("🥇", "🥈", "🥉")


async def _top(session, column: str, limit: int = 10) -> list[tuple[Member, ContributionScore]]:
    col = getattr(ContributionScore, column)
    result = await session.execute(
        select(Member, ContributionScore)
        .join(ContributionScore, ContributionScore.member_id == Member.id)
        .order_by(col.desc())
        .limit(limit)
    )
    return list(result.all())


def _lines(rows: list[tuple[Member, ContributionScore]], attr: str, *, silver: bool = False) -> str:
    out = []
    for i, (member, score) in enumerate(rows):
        medal = MEDALS[i] if i < 3 else f"`{i+1:02d}`"
        value = getattr(score, attr)
        shown = format_silver(value) if silver else f"{value:,}".replace(",", " ")
        name = member.discord_name or member.albion_name or "?"
        out.append(f"{medal} **{name}** — {shown}")
    return "\n".join(out) or "*aucun*"


async def build_leaderboard_embeds() -> list[discord.Embed]:
    async with session_scope() as session:
        orders = await _top(session, "order_points_all_time")
        monthly = await _top(session, "order_points_monthly")
        fame = await _top(session, "total_fame")
        dons = await _top(session, "total_silver_donated")
    e1 = info_embed("🎯 TOP CONTRIBUTEURS ORDRES", _lines(orders, "order_points_all_time"))
    e2 = info_embed("📅 TOP ORDRES DU MOIS", _lines(monthly, "order_points_monthly"))
    e3 = info_embed("⚔️ TOP FAME", _lines(fame, "total_fame"))
    e4 = info_embed("💰 TOP DONATEURS", _lines(dons, "total_silver_donated", silver=True))
    return [e1, e2, e3, e4]


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = AlbionAPIClient()
        self._message_ids: list[int] = []

    async def cog_unload(self) -> None:
        await self.api.close()

    async def refresh_fame_from_api(self) -> None:
        async with session_scope() as session:
            members = list((await session.execute(select(Member))).scalars().all())
        for member in members:
            if not member.albion_player_id and not member.albion_name:
                continue
            try:
                if member.albion_player_id:
                    data = await self.api.get_player(member.albion_player_id)
                else:
                    search = await self.api.search_players(member.albion_name or "")
                    players = (search.get("players") if isinstance(search, dict) else None) or []
                    if not players:
                        continue
                    data = players[0]
                    pid = data.get("Id")
                    if pid:
                        async with session_scope() as session:
                            db = await session.get(Member, member.id)
                            if db:
                                db.albion_player_id = str(pid)
                        data = await self.api.get_player(str(pid))
                total = int((data or {}).get("KillFame") or 0) + int((data or {}).get("DeathFame") or 0)
                # Fame totale joueur
                fame = int((data or {}).get("LifetimeStatistics", {}).get("PvE", {}).get("Total") or 0)
                fame += int((data or {}).get("KillFame") or 0)
                if fame <= 0:
                    fame = total
                async with session_scope() as session:
                    score = await session.scalar(select(ContributionScore).where(ContributionScore.member_id == member.id))
                    if score:
                        score.total_fame = fame
            except (AlbionAPIError, Exception):
                LOGGER.debug("Fame skip %s", member.albion_name)

    async def post_or_update(self, guild: discord.Guild) -> None:
        channel = find_channel(guild, "leaderboard")
        if channel is None:
            return
        await self.refresh_fame_from_api()
        embeds = await build_leaderboard_embeds()
        if len(self._message_ids) == 4:
            ok = True
            for mid, embed in zip(self._message_ids, embeds, strict=False):
                try:
                    msg = await channel.fetch_message(mid)
                    await msg.edit(embed=embed)
                except discord.HTTPException:
                    ok = False
                    break
            if ok:
                return
        self._message_ids = []
        for embed in embeds:
            msg = await channel.send(embed=embed)
            self._message_ids.append(msg.id)

    @app_commands.command(name="leaderboard", description="Affiche un classement.")
    @app_commands.choices(
        filtre=[
            app_commands.Choice(name="ordres", value="ordres"),
            app_commands.Choice(name="fame", value="fame"),
            app_commands.Choice(name="dons", value="dons"),
            app_commands.Choice(name="mensuel", value="mensuel"),
            app_commands.Choice(name="global", value="global"),
        ]
    )
    async def leaderboard_cmd(self, interaction: discord.Interaction, filtre: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer()
        embeds = await build_leaderboard_embeds()
        mapping = {"ordres": 0, "mensuel": 1, "fame": 2, "dons": 3}
        if filtre is None or filtre.value == "global":
            await interaction.followup.send(embeds=embeds)
            return
        await interaction.followup.send(embed=embeds[mapping[filtre.value]])

    @app_commands.command(name="setup_leaderboard", description="Poste les 4 classements dans #leaderboard.")
    @app_commands.guild_only()
    async def setup_leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        assert interaction.guild
        await self.post_or_update(interaction.guild)
        await interaction.followup.send("Leaderboard posté / mis à jour.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
