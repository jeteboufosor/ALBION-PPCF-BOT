"""Phase 6 — Marché Fort Sterling : prix, watchlist, historique."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.crud import get_or_create_member
from bot.database.engine import session_scope
from bot.database.models import MarketWatch
from bot.services.market_api import FORT_STERLING, MarketAPIClient, MarketAPIError
from bot.utils.embeds import error_embed, info_embed, success_embed, warning_embed

LOGGER = logging.getLogger(__name__)


def _fmt_price(value: int | None) -> str:
    if not value:
        return "—"
    return f"{value:,}".replace(",", " ")


class Market(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = MarketAPIClient()

    async def cog_unload(self) -> None:
        await self.api.close()

    @app_commands.command(name="prix", description="Prix actuel Fort Sterling + tendance.")
    async def prix(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await self.api.get_prices(item, locations=FORT_STERLING)
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)), ephemeral=True)
            return
        if not rows:
            await interaction.followup.send(embed=error_embed("Item inconnu", "Utilise l'ID Albion (ex: T6_WOOD)."), ephemeral=True)
            return
        row = rows[0]
        embed = info_embed(
            f"🛒 {item}",
            f"**Fort Sterling**\n"
            f"Vente min : **{_fmt_price(row.get('sell_price_min'))}**\n"
            f"Achat max : **{_fmt_price(row.get('buy_price_max'))}**",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="prix_comparer", description="Compare Fort Sterling aux autres villes.")
    async def prix_comparer(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await self.api.compare_cities(item)
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)), ephemeral=True)
            return
        lines = []
        for row in rows[:12]:
            city = row.get("city") or row.get("location") or "?"
            lines.append(f"**{city}** — vente {_fmt_price(row.get('sell_price_min'))}")
        await interaction.followup.send(embed=info_embed(f"🏙️ {item}", "\n".join(lines) or "aucune donnée"), ephemeral=True)

    @app_commands.command(name="black_market", description="Prix Black Market Caerleon.")
    async def black_market(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await self.api.get_prices(item, locations="Black Market")
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)), ephemeral=True)
            return
        row = rows[0] if rows else {}
        await interaction.followup.send(
            embed=info_embed(f"⬛ Black Market — {item}", f"Vente min : **{_fmt_price(row.get('sell_price_min'))}**"),
            ephemeral=True,
        )

    @app_commands.command(name="historique_prix", description="Historique ASCII 7 jours.")
    async def historique_prix(self, interaction: discord.Interaction, item: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await self.api.get_history(item, location=FORT_STERLING)
        except MarketAPIError as exc:
            await interaction.followup.send(embed=error_embed("API marché", str(exc)), ephemeral=True)
            return
        prices = [int(r.get("avg_price") or r.get("data", [{}])[-1].get("avg_price") or 0) for r in rows[:14]]
        prices = [p for p in prices if p > 0][-7:]
        if not prices:
            await interaction.followup.send(embed=warning_embed("Pas d'historique"), ephemeral=True)
            return
        mx = max(prices)
        bars = "".join("█" if p / mx > 0.66 else "▄" if p / mx > 0.33 else "▁" for p in prices)
        await interaction.followup.send(embed=info_embed(f"📈 {item}", f"`{bars}`\nDernier : {_fmt_price(prices[-1])}"), ephemeral=True)

    @app_commands.command(name="watchlist_ajouter", description="Alerte si le prix sort d'une fourchette.")
    async def watchlist_ajouter(
        self,
        interaction: discord.Interaction,
        item: str,
        prix_bas: int,
        prix_haut: int,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with session_scope() as session:
            member = await get_or_create_member(session, discord_id=interaction.user.id, discord_name=interaction.user.display_name)
            watch = MarketWatch(
                member_id=member.id,
                item_id=item,
                item_name=item,
                low_threshold=prix_bas,
                high_threshold=prix_haut,
            )
            session.add(watch)
            await session.flush()
            wid = watch.id
        await interaction.followup.send(embed=success_embed("Alerte créée", f"id `{wid}` — {item} [{prix_bas}-{prix_haut}]"), ephemeral=True)

    @app_commands.command(name="watchlist", description="Liste tes alertes prix.")
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

    @app_commands.command(name="craft_profit", description="Lien de rentabilité craft (albion.tools).")
    async def craft_profit(self, interaction: discord.Interaction, item: str) -> None:
        url = f"https://albion.tools/crafting?item={item}"
        await interaction.response.send_message(embed=info_embed("🔨 Craft profit", f"[Ouvrir sur albion.tools]({url})"), ephemeral=True)


def warning_like(text: str) -> discord.Embed:
    return error_embed(text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Market(bot))
