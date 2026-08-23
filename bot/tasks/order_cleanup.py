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
from bot.utils.embeds import format_order_number, info_embed
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
            .where(Order.status.in_(("completed", "cancelled")), Order.archived_at.is_(None))
        )
        orders = list(result.scalars().all())

    for order in orders:
        ready = False
        if order.status == "completed" and order.completed_at and order.completed_at <= cutoff:
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
            people = sorted(order.participants, key=lambda p: p.contribution_amount, reverse=True)
            lines = [f"{p.member.discord_name if p.member else '?'} — {p.contribution_amount} ({p.points_awarded} pts)" for p in people]
            embed = info_embed(
                f"📜 Archive {format_order_number(order.order_number)} — {order.title}",
                order.description,
            )
            embed.add_field(name="Statut", value=order.status, inline=True)
            embed.add_field(name="Total", value=f"{order.current_amount}/{order.target_amount}", inline=True)
            embed.add_field(name="Classement", value="\n".join(lines) or "aucun", inline=False)
            await archive.send(embed=embed)

    async with session_scope() as session:
        db = await session.get(Order, order.id)
        if db is not None:
            db.archived_at = utcnow()
            db.message_id = None
