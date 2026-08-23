"""Sync killboard toutes les 5 minutes."""

from __future__ import annotations

import logging

from discord.ext import commands

LOGGER = logging.getLogger(__name__)


async def run_killboard_sync(bot: commands.Bot) -> None:
    cog = bot.get_cog("Killboard")
    if cog is None:
        return
    try:
        posted = await cog.sync_kills()  # type: ignore[attr-defined]
        if posted:
            LOGGER.info("%s kill(s) postés", posted)
    except Exception:
        LOGGER.exception("killboard_sync a échoué")
