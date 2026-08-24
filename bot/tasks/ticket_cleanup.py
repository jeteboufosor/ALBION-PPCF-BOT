"""Ferme les tickets inactifs depuis 7 jours (rappel 24h avant)."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord.ext import commands
from sqlalchemy import select

from bot.database.engine import session_scope
from bot.database.models import Ticket, utcnow

LOGGER = logging.getLogger(__name__)


async def run_ticket_cleanup(bot: commands.Bot) -> int:
    from bot.cogs.tickets import close_ticket

    now = utcnow()
    warn_after = now - timedelta(days=6)
    close_after = now - timedelta(days=7)
    closed = 0

    async with session_scope() as session:
        tickets = list((await session.execute(select(Ticket).where(Ticket.status == "open"))).scalars().all())

    for ticket in tickets:
        last = ticket.last_activity_at or ticket.created_at
        if last <= close_after:
            await close_ticket(bot, ticket.id, closer_id=0)
            closed += 1
            continue
        if last <= warn_after and ticket.warned_inactive_at is None:
            channel = bot.get_channel(ticket.channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send("⏳ Ticket inactif : fermeture automatique dans 24h s'il n'y a pas de message.")
                except discord.HTTPException:
                    pass
            async with session_scope() as session:
                db = await session.get(Ticket, ticket.id)
                if db:
                    db.warned_inactive_at = now
    if closed:
        LOGGER.info("%s ticket(s) fermés pour inactivité", closed)
    return closed
