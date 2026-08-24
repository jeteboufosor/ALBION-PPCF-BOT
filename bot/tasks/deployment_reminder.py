"""Rappels et lancement auto des déploiements."""

from __future__ import annotations

import logging

from discord.ext import commands

LOGGER = logging.getLogger(__name__)


async def run_deployment_reminders(bot: commands.Bot) -> None:
    from bot.cogs.deployment import process_deployment_timers

    try:
        await process_deployment_timers(bot)
    except Exception:
        LOGGER.exception("deployment_reminder a échoué")
