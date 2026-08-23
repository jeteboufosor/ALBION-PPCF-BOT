"""Phase 7 — Classement unique avec navigation catégorie + période."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.engine import session_scope
from bot.database.models import ContributionScore, Member
from bot.services.albion_api import AlbionAPIClient, AlbionAPIError
from bot.utils.embeds import format_silver
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)
MEDALS = ("🥇", "🥈", "🥉")

CATS = ("ordres", "fame", "dons")
PERIODS = ("month", "all")

CAT_META: dict[str, dict[str, str]] = {
    "ordres": {"emoji": "🎯", "label": "Ordres", "title": "ORDRES"},
    "fame": {"emoji": "⚔️", "label": "Fame", "title": "FAME"},
    "dons": {"emoji": "💰", "label": "Dons", "title": "DONATEURS"},
}
PERIOD_META = {
    "month": {"label": "Mensuel", "hint": "ce mois-ci"},
    "all": {"label": "All-time", "hint": "depuis toujours"},
}
COLUMNS = {
    ("ordres", "all"): "order_points_all_time",
    ("ordres", "month"): "order_points_monthly",
    ("fame", "all"): "total_fame",
    ("fame", "month"): "fame_monthly",
    ("dons", "all"): "total_silver_donated",
    ("dons", "month"): "silver_donated_monthly",
}


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
        medal = MEDALS[i] if i < 3 else f"`{i + 1:02d}`"
        value = getattr(score, attr)
        shown = format_silver(value) if silver else f"{value:,}".replace(",", " ")
        name = member.discord_name or member.albion_name or "?"
        mention = f"<@{member.discord_id}>" if member.discord_id else name
        out.append(f"{medal}  {mention}  ·  **{shown}**")
    return "\n".join(out) or "*aucun score*"


async def build_leaderboard_embed(cat: str = "ordres", period: str = "month") -> discord.Embed:
    if cat not in CAT_META:
        cat = "ordres"
    if period not in PERIOD_META:
        period = "month"
    column = COLUMNS[(cat, period)]
    async with session_scope() as session:
        rows = await _top(session, column)
    meta = CAT_META[cat]
    per = PERIOD_META[period]
    rule = "━" * 26
    embed = discord.Embed(
        description=(
            f"-# CLASSEMENT  ·  {per['label'].upper()}\n"
            f"{rule}\n\n"
            f"## {meta['emoji']}  TOP 10 {meta['title']}\n"
            f"-# {per['hint']}\n\n"
            f"{_lines(rows, column, silver=cat == 'dons')}"
        ),
        color=discord.Color.gold() if cat == "dons" else discord.Color.dark_gold(),
    )
    embed.set_footer(text="Albion PPCF • Fort Sterling  ·  ⏳ période")
    return embed


def other_period(period: str) -> str:
    return "all" if period == "month" else "month"


class LeaderboardNavItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"lb:(?P<kind>cat|per):(?P<cat>ordres|fame|dons):(?P<per>month|all):(?P<val>ordres|fame|dons|toggle)",
):
    def __init__(self, kind: str, cat: str, period: str, value: str) -> None:
        if kind == "cat":
            meta = CAT_META[value]
            super().__init__(
                discord.ui.Button(
                    label=meta["label"],
                    emoji=meta["emoji"],
                    style=discord.ButtonStyle.primary if value == cat else discord.ButtonStyle.secondary,
                    disabled=value == cat,
                    custom_id=f"lb:cat:{cat}:{period}:{value}",
                )
            )
        else:
            super().__init__(
                discord.ui.Button(
                    label=PERIOD_META[period]["label"],
                    emoji="⏳",
                    style=discord.ButtonStyle.success,
                    custom_id=f"lb:per:{cat}:{period}:toggle",
                )
            )
        self.kind = kind
        self.cat = cat
        self.period = period
        self.value = value

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> LeaderboardNavItem:
        return cls(match["kind"], match["cat"], match["per"], match["val"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        if self.kind == "cat":
            cat, period = self.value, self.period
        else:
            cat, period = self.cat, other_period(self.period)
        embed = await build_leaderboard_embed(cat, period)
        try:
            await interaction.message.edit(embed=embed, view=LeaderboardView(cat, period))
        except discord.HTTPException:
            LOGGER.exception("Maj leaderboard impossible")


class LeaderboardView(discord.ui.View):
    def __init__(self, cat: str = "ordres", period: str = "month") -> None:
        super().__init__(timeout=None)
        for key in CATS:
            self.add_item(LeaderboardNavItem("cat", cat, period, key))
        self.add_item(LeaderboardNavItem("per", cat, period, "left"))
        self.add_item(
            discord.ui.Button(
                label=PERIOD_META[period]["label"],
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id=f"lb:per:{cat}:{period}:{period}",
            )
        )
        self.add_item(LeaderboardNavItem("per", cat, period, "right"))


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = AlbionAPIClient()
        self._message_id: int | None = None

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(LeaderboardNavItem)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(LeaderboardNavItem)
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
                fame = int((data or {}).get("LifetimeStatistics", {}).get("PvE", {}).get("Total") or 0)
                fame += int((data or {}).get("KillFame") or 0)
                if fame <= 0:
                    fame = total
                async with session_scope() as session:
                    score = await session.scalar(
                        select(ContributionScore).where(ContributionScore.member_id == member.id)
                    )
                    if score:
                        if not score.fame_baseline:
                            score.fame_baseline = fame
                        score.total_fame = fame
                        score.fame_monthly = max(0, fame - (score.fame_baseline or 0))
            except (AlbionAPIError, Exception):
                LOGGER.debug("Fame skip %s", member.albion_name)

    async def post_or_update(self, guild: discord.Guild, *, cat: str = "ordres", period: str = "month") -> None:
        channel = find_channel(guild, "leaderboard")
        if channel is None:
            return
        await self.refresh_fame_from_api()
        embed = await build_leaderboard_embed(cat, period)
        view = LeaderboardView(cat, period)
        if self._message_id:
            try:
                msg = await channel.fetch_message(self._message_id)
                await msg.edit(embed=embed, view=view)
                return
            except discord.HTTPException:
                pass
        msg = await channel.send(embed=embed, view=view)
        self._message_id = msg.id

    @app_commands.command(name="leaderboard", description="Affiche le classement (1 embed, boutons de nav).")
    @app_commands.choices(
        categorie=[
            app_commands.Choice(name="ordres", value="ordres"),
            app_commands.Choice(name="fame", value="fame"),
            app_commands.Choice(name="dons", value="dons"),
        ],
        periode=[
            app_commands.Choice(name="mensuel", value="month"),
            app_commands.Choice(name="all-time", value="all"),
        ],
    )
    async def leaderboard_cmd(
        self,
        interaction: discord.Interaction,
        categorie: app_commands.Choice[str] | None = None,
        periode: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()
        cat = categorie.value if categorie else "ordres"
        period = periode.value if periode else "month"
        embed = await build_leaderboard_embed(cat, period)
        await interaction.followup.send(embed=embed, view=LeaderboardView(cat, period))

    @app_commands.command(name="setup_leaderboard", description="Poste le classement unique dans #leaderboard.")
    @app_commands.guild_only()
    async def setup_leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        assert interaction.guild
        await self.post_or_update(interaction.guild)
        await interaction.followup.send("Leaderboard posté / mis à jour (1 embed + boutons).", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leaderboard(bot))
