"""Rapport santé lundi 09h."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from discord.ext import commands

from bot.database.engine import IS_POSTGRES
from bot.utils.embeds import info_embed
from bot.utils.permissions import find_channel

LOGGER = logging.getLogger(__name__)


async def run_weekly_health(bot: commands.Bot) -> None:
    started = getattr(bot, "started_at", datetime.now(UTC))
    uptime = datetime.now(UTC) - started
    embed = info_embed(
        "🩺 Rapport hebdo",
        f"Uptime : **{int(uptime.total_seconds()//3600)} h**\n"
        f"Base : **{'PostgreSQL' if IS_POSTGRES else 'SQLite'}**\n"
        f"Latence : **{round(bot.latency*1000)} ms**\n"
        f"Guildes : **{len(bot.guilds)}**",
    )
    for guild in bot.guilds:
        channel = find_channel(guild, "bot_alerts")
        if channel:
            await channel.send(embed=embed)
    LOGGER.info("Rapport hebdo posté")
