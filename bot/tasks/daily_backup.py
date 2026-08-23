"""Backup quotidien 04h00 Europe/Berlin."""

from __future__ import annotations

import logging

from discord.ext import commands

LOGGER = logging.getLogger(__name__)


async def run_daily_backup(bot: commands.Bot) -> None:
    from bot.cogs.backup import send_backup

    for guild in bot.guilds:
        try:
            await send_backup(bot, guild)
            LOGGER.info("Backup auto envoyé sur %s", guild.name)
        except Exception:
            LOGGER.exception("Backup auto échoué (%s)", guild.name)
