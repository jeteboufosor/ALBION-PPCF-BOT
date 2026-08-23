"""Phase 6 — Marché Fort Sterling (réponses publiques)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import MarketWatch
from bot.services.item_lookup import item_autocomplete, resolve_item_query
from bot.services.item_service import ItemService
from bot.services.market_api import FORT_STERLING, MarketAPIClient, MarketAPIError
from bot.utils.embeds import error_embed, info_embed, success_embed, warning_embed

LOGGER = logging.getLogger(__name__)


def _fmt_price(value: int | float | None) -> str:
    if not value:
        return "—"
    return f"{int(value):,}".replace(",", " ")


def _price_chart(values: list[int]) -> str:
    """Courbe unicode type terminal (8 lignes)."""

    if not values:
        return ""
    width = min(18, max(8, len(values)))
    # ré-échantillonne
    pts: list[int] = []
    for i in range(width):
        idx = int(i * (len(values) - 1) / max(1, width - 1))
        pts.append(values[idx])
    lo, hi = min(pts), max(pts)
    span = max(1, hi - lo)
    height = 8
    grid = [[" " for _ in range(width)] for _ in range(height)]
    for x, v in enumerate(pts):
        y = height - 1 - int(round((v - lo) / span * (height - 1)))
        grid[y][x] = "●"
        for fill in range(y + 1, height):
            if grid[fill][x] == " ":
                grid[fill][x] = "│"
    # relie les points
    for x in range(width - 1):
        y1 = height - 1 - int(round((pts[x] - lo) / span * (height - 1)))
        y2 = height - 1 - int(round((pts[x + 1] - lo) / span * (height - 1)))
        step = 1 if y2 >= y1 else -1
        for y in range(y1, y2, step):
            if grid[y][x] == " ":
                grid[y][x] = "╱" if step < 0 else "╲"
    lines = []
    for i, row in enumerate(grid):
        label = _fmt_price(hi if i == 0 else lo if i == height - 1 else None)
        prefix = f"{label:>7}" if label != "—" else "       "
        lines.append(f"{prefix} ┤{''.join(row)}")
    lines.append(f"        └{'─' * width}")
    lines.append(f"         {-len(values)+1:>3}j{' ' * (width - 8)}0")
    return "```\n" + "\n".join(lines) + "\n```"


class Market(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = MarketAPIClient()
        self.items = ItemService()

    async def cog_unload(self) -> None:
        await self.api.close()
        await self.items.close()

    async def _resolve(self, raw: str) -> str:
        hits = await resolve_item_query(raw)
        return hits[0][0] if hits else raw.strip().upper()

    async def _icon(self, item_id: str) -> str:
        try:
            return await self.items.get_icon_url(item_id)
        except Exception:
            return ""

    @app_commands.command(name="prix", description="Prix Fort Sterling (visible par tout le salon).")
    @app_commands.autocomplete(item=item_autocomplete)
    async def prix(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=False)
        item = await self._resolve(item)
        try:
            rows = await self.api.get_prices(item, locations=FORT_STERLING)
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)))
            return
        if not rows:
            await interaction.followup.send(embed=error_embed("Item inconnu", "Tape `bois t6`, `minerai t5`…"))
            return
        row = rows[0]
        embed = info_embed(
            f"🛒 {item}",
            f"**Fort Sterling**\nVente min : **{_fmt_price(row.get('sell_price_min'))}**\nAchat max : **{_fmt_price(row.get('buy_price_max'))}**",
        )
        icon = await self._icon(item)
        if icon:
            embed.set_thumbnail(url=icon)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="prix_comparer", description="Compare les villes.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def prix_comparer(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=False)
        item = await self._resolve(item)
        try:
            rows = await self.api.compare_cities(item)
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)))
            return
        lines = []
        for row in rows[:12]:
            city = row.get("city") or row.get("location") or "?"
            lines.append(f"**{city}** — vente {_fmt_price(row.get('sell_price_min'))}")
        embed = info_embed(f"🏙️ {item}", "\n".join(lines) or "aucune donnée")
        icon = await self._icon(item)
        if icon:
            embed.set_thumbnail(url=icon)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="black_market", description="Prix Black Market.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def black_market(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=False)
        item = await self._resolve(item)
        try:
            rows = await self.api.get_prices(item, locations="Black Market")
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)))
            return
        row = rows[0] if rows else {}
        await interaction.followup.send(
            embed=info_embed(f"⬛ Black Market — {item}", f"Vente min : **{_fmt_price(row.get('sell_price_min'))}**")
        )

    @app_commands.command(name="historique_prix", description="Courbe de prix Fort Sterling.")
    @app_commands.describe(jours="Nombre de jours (1 à 30, défaut 7)")
    @app_commands.autocomplete(item=item_autocomplete)
    async def historique_prix(self, interaction: discord.Interaction, item: str, jours: app_commands.Range[int, 1, 30] = 7) -> None:
        await interaction.response.defer(ephemeral=False)
        end = datetime.now(UTC)
        start = end - timedelta(days=int(jours))
        try:
            rows = await self.api.get_history(
                item,
                location=FORT_STERLING,
                date=start.strftime("%m-%d-%Y"),
            )
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)))
            return
        prices: list[int] = []
        if rows and isinstance(rows, list):
            first = rows[0]
            data = first.get("data") if isinstance(first, dict) else None
            if isinstance(data, list):
                for point in data:
                    avg = point.get("avg_price") or point.get("price")
                    if avg:
                        prices.append(int(avg))
            else:
                for r in rows:
                    avg = r.get("avg_price") if isinstance(r, dict) else None
                    if avg:
                        prices.append(int(avg))
        prices = prices[-max(7, int(jours)) :]
        if not prices:
            await interaction.followup.send(embed=warning_embed("Pas d'historique pour cette période"))
            return
        curve = _price_chart(prices)
        embed = info_embed(
            f"📈 {item} — {jours} jour(s)",
            f"{curve}Min **{_fmt_price(min(prices))}**  ·  Max **{_fmt_price(max(prices))}**  ·  Dernier **{_fmt_price(prices[-1])}**",
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="watchlist_ajouter", description="Alerte si le prix sort d'une fourchette.")
    @app_commands.autocomplete(item=item_autocomplete)
    async def watchlist_ajouter(self, interaction: discord.Interaction, item: str, prix_bas: int, prix_haut: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            member = await get_or_create_member(session, discord_id=interaction.user.id, discord_name=interaction.user.display_name)
            watch = MarketWatch(member_id=member.id, item_id=item, item_name=item, low_threshold=prix_bas, high_threshold=prix_haut)
            session.add(watch)
            await session.flush()
            wid = watch.id
        await interaction.followup.send(embed=success_embed("Alerte créée", f"id `{wid}` — {item}"), ephemeral=True)

    @app_commands.command(name="watchlist", description="Tes alertes (privé).")
    async def watchlist(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            member = await get_or_create_member(session, discord_id=interaction.user.id, discord_name=interaction.user.display_name)
            rows = list((await session.execute(select(MarketWatch).where(MarketWatch.member_id == member.id, MarketWatch.is_active.is_(True)))).scalars().all())
        lines = [f"`{w.id}` {w.item_name}  {w.low_threshold}–{w.high_threshold}" for w in rows]
        await interaction.followup.send(embed=info_embed("Watchlist", "\n".join(lines) or "*vide*"), ephemeral=True)

    @app_commands.command(name="watchlist_supprimer", description="Supprime une alerte.")
    async def watchlist_supprimer(self, interaction: discord.Interaction, id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            watch = await session.get(MarketWatch, id)
            if watch is None:
                await interaction.followup.send(embed=error_embed("Introuvable"), ephemeral=True)
                return
            watch.is_active = False
        await interaction.followup.send(embed=success_embed("Alerte retirée"), ephemeral=True)

    @app_commands.command(name="craft_profit", description="Rentabilité craft (lien albion.tools).")
    @app_commands.autocomplete(item=item_autocomplete)
    async def craft_profit(self, interaction: discord.Interaction, item: str) -> None:
        url = f"https://albion.tools/crafting?item={item}"
        await interaction.response.send_message(embed=info_embed("🔨 Craft profit", f"[Ouvrir sur albion.tools]({url})"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Market(bot))
