"""Met à jour les ordres fame gathering / PvE depuis l'API Albion."""

from __future__ import annotations

import logging

from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.database.engine import session_scope
from bot.database.models import Order, OrderParticipant
from bot.services.albion_api import AlbionAPIClient
from bot.services.fame import fetch_member_fame

LOGGER = logging.getLogger(__name__)
FAME_TYPES = ("gathering_fame", "pve_fame")


async def run_order_fame_sync(bot: commands.Bot) -> int:
    from bot.cogs.orders import _sync_current_amount, complete_order, refresh_order_message

    api = AlbionAPIClient()
    updated = 0
    to_complete: list[int] = []
    try:
        async with session_scope() as session:
            result = await session.execute(
                select(Order)
                .options(selectinload(Order.participants).selectinload(OrderParticipant.member))
                .where(Order.status == "active", Order.objective_type.in_(FAME_TYPES))
            )
            orders = list(result.scalars().all())

            for order in orders:
                changed = False
                for part in order.participants:
                    member = part.member
                    if member is None:
                        continue
                    fame, pid = await fetch_member_fame(
                        api,
                        player_id=member.albion_player_id,
                        name=member.albion_name,
                        kind=order.objective_type,
                    )
                    if pid and not member.albion_player_id:
                        member.albion_player_id = pid
                    if part.baseline_fame is None:
                        part.baseline_fame = fame
                        changed = True
                        continue
                    gained = max(0, fame - part.baseline_fame)
                    if gained != part.contribution_amount:
                        part.contribution_amount = gained
                        changed = True
                if not changed:
                    continue
                _sync_current_amount(order)
                total = order.current_amount or 1
                for part in order.participants:
                    part.contribution_percent = part.contribution_amount * 100 / total
                await refresh_order_message(bot, order)
                updated += 1
                if order.current_amount >= order.target_amount:
                    to_complete.append(order.id)
    finally:
        await api.close()

    for oid in to_complete:
        await complete_order(bot, oid, reason="quota")
    if updated:
        LOGGER.info("Fame ordres: %s maj, %s clôturé(s)", updated, len(to_complete))
    return updated
