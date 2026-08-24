"""Alertes watchlist + rapport 20h #alertes-prix."""

from __future__ import annotations

import logging
from datetime import timedelta

from discord.ext import commands
from sqlalchemy import select

from bot.database.engine import session_scope
from bot.database.models import MarketPriceSnapshot, MarketWatch, Member, utcnow
from bot.services.market_api import FORT_STERLING, MarketAPIClient, MarketAPIError
from bot.utils.embeds import format_silver, info_embed, warning_embed
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)
COOLDOWN = timedelta(hours=4)


def _sell(row: dict) -> int:
    return int(row.get("sell_price_min") or 0)


async def run_price_watch(bot: commands.Bot) -> int:
    """Vérifie les fourchettes et ping #alertes-prix si hors seuils."""

    api = MarketAPIClient()
    triggered = 0
    try:
        async with session_scope() as session:
            watches = list(
                (await session.execute(select(MarketWatch).where(MarketWatch.is_active.is_(True)))).scalars().all()
            )
            if not watches:
                return 0
            now = utcnow()
            by_item: dict[str, list[MarketWatch]] = {}
            for watch in watches:
                by_item.setdefault(watch.item_id, []).append(watch)

            prices: dict[str, int] = {}
            for item_id, group in by_item.items():
                city = group[0].city or FORT_STERLING
                try:
                    rows = await api.get_prices(item_id, locations=city)
                except MarketAPIError:
                    LOGGER.debug("Prix indisponible %s", item_id)
                    continue
                if not rows:
                    continue
                sell = _sell(rows[0])
                prices[item_id] = sell
                session.add(
                    MarketPriceSnapshot(
                        item_id=item_id,
                        item_name=group[0].item_name,
                        city=city,
                        sell_price_min=sell or None,
                        buy_price_max=int(rows[0].get("buy_price_max") or 0) or None,
                    )
                )

            alerts: list[tuple[int, int, str]] = []
            for item_id, group in by_item.items():
                sell = prices.get(item_id)
                if not sell:
                    continue
                for watch in group:
                    if watch.last_triggered_at and (now - watch.last_triggered_at) < COOLDOWN:
                        continue
                    kind = ""
                    if watch.low_threshold is not None and sell <= watch.low_threshold:
                        kind = "bas"
                    elif watch.high_threshold is not None and sell >= watch.high_threshold:
                        kind = "haut"
                    if not kind:
                        continue
                    watch.last_triggered_at = now
                    alerts.append((watch.id, sell, kind))

        if not alerts:
            return 0

        for watch_id, sell, kind in alerts:
            async with session_scope() as session:
                watch = await session.get(MarketWatch, watch_id)
                if watch is None:
                    continue
                member = await session.get(Member, watch.member_id) if watch.member_id else None
                mention = f"<@{member.discord_id}>" if member else None
                name = watch.item_name
                uid = watch.item_id
                low, high = watch.low_threshold, watch.high_threshold
            arrow = "📉" if kind == "bas" else "📈"
            seuil = low if kind == "bas" else high
            embed = warning_embed(
                "Alerte prix",
                f"{arrow} **{name}** (`{uid}`)\n"
                f"Fort Sterling : **{format_silver(sell)}**\n"
                f"Seuil {kind} : **{format_silver(seuil or 0)}**\n"
                f"id `{watch_id}`",
            )
            for guild in bot.guilds:
                channel = find_channel(guild, "price_alerts")
                if channel:
                    await channel.send(content=mention, embed=embed)
            triggered += 1
        return triggered
    finally:
        await api.close()


async def run_daily_price_report(bot: commands.Bot) -> None:
    """Récap 20h des items suivis."""

    api = MarketAPIClient()
    try:
        async with session_scope() as session:
            watches = list(
                (await session.execute(select(MarketWatch).where(MarketWatch.is_active.is_(True)))).scalars().all()
            )
        if not watches:
            return
        lines: list[str] = []
        seen: set[str] = set()
        for watch in watches:
            if watch.item_id in seen:
                continue
            seen.add(watch.item_id)
            try:
                rows = await api.get_prices(watch.item_id, locations=watch.city or FORT_STERLING)
            except MarketAPIError:
                lines.append(f"• **{watch.item_name}** — indisponible")
                continue
            sell = _sell(rows[0]) if rows else 0
            lines.append(f"• **{watch.item_name}** — {format_silver(sell) if sell else '—'}")
        embed = info_embed("📊 Rapport prix 20h", "\n".join(lines[:25]) or "*aucune watchlist*")
        for guild in bot.guilds:
            channel = find_channel(guild, "price_alerts")
            if channel:
                await channel.send(embed=embed)
        LOGGER.info("Rapport prix 20h posté (%s items)", len(lines))
    finally:
        await api.close()
