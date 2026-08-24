"""Archive les ordres terminés (24h) et supprime les quêtes expirées (6h)."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.database.engine import session_scope
from bot.database.models import Order, OrderParticipant, Quest, QuestParticipant, utcnow
from bot.utils.embeds import format_order_number
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)


async def run_order_cleanup(bot: commands.Bot) -> tuple[int, int]:
    archived = 0
    removed_quests = 0
    cutoff = utcnow() - timedelta(hours=24)

    async with session_scope() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.participants).selectinload(OrderParticipant.member))
            .where(Order.status.in_(("completed", "cancelled", "expired")), Order.archived_at.is_(None))
        )
        orders = list(result.scalars().all())

    for order in orders:
        ready = False
        if order.status in {"completed", "expired"} and order.completed_at and order.completed_at <= cutoff:
            ready = True
        if order.status == "cancelled" and order.cancelled_at and order.cancelled_at <= cutoff:
            ready = True
        if not ready:
            continue
        await _archive_order(bot, order)
        archived += 1

    async with session_scope() as session:
        qres = await session.execute(
            select(Quest)
            .options(selectinload(Quest.participants).selectinload(QuestParticipant.member))
            .where(Quest.status == "completed", Quest.delete_after_at.is_not(None), Quest.delete_after_at <= utcnow())
        )
        quests = list(qres.scalars().all())

    for quest in quests:
        if quest.channel_id and quest.message_id:
            channel = bot.get_channel(quest.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(quest.message_id)
                    await msg.delete()
                except discord.HTTPException:
                    pass
        async with session_scope() as session:
            db_q = await session.get(Quest, quest.id)
            if db_q is not None:
                db_q.status = "archived"
        removed_quests += 1

    if archived or removed_quests:
        LOGGER.info("Cleanup: %s ordres archivés, %s quêtes retirées", archived, removed_quests)
    return archived, removed_quests


async def _archive_order(bot: commands.Bot, order: Order) -> None:
    guild = None
    if order.channel_id:
        ch = bot.get_channel(order.channel_id)
        if isinstance(ch, discord.TextChannel):
            guild = ch.guild
            try:
                msg = await ch.fetch_message(order.message_id) if order.message_id else None
                if msg:
                    await msg.delete()
            except discord.HTTPException:
                pass
    if guild is None:
        for g in bot.guilds:
            guild = g
            break
    if guild is not None:
        archive = find_channel(guild, "past_orders")
        if archive is not None:
            from bot.cogs.orders import build_order_embed
            from bot.utils.embeds import discord_timestamp

            embed = build_order_embed(order)
            status_fr = {"completed": "✅ Réussi", "expired": "💀 Échoué", "cancelled": "❌ Annulé"}.get(
                order.status, order.status
            )
            when = order.completed_at or order.cancelled_at
            extra = [
                f"**Archive** {format_order_number(order.order_number)}",
                f"**Issue :** {status_fr}",
            ]
            if order.close_reason:
                extra.append(f"**Motif :** `{order.close_reason}`")
            if when:
                extra.append(f"**Clôturé :** {discord_timestamp(when, 'F')} — {discord_timestamp(when, 'R')}")
            extra.append(f"**Quota :** {order.current_amount:,} / {order.target_amount:,}".replace(",", " "))
            if order.points_value:
                extra.append(f"**Points / contributeur :** +{order.points_value}" if order.status == "completed" else "**Points :** 0 (échec / annulation)")
            embed.description = (embed.description or "") + "\n\n" + "\n".join(extra)
            embed.title = f"📜 Archive {format_order_number(order.order_number)}"
            await archive.send(embed=embed)

    async with session_scope() as session:
        db = await session.get(Order, order.id)
        if db is not None:
            db.archived_at = utcnow()
            db.message_id = None
