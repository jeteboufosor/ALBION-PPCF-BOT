"""Planificateur APScheduler (tâches récurrentes)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from bot.tasks.order_cleanup import run_order_cleanup

LOGGER = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Berlin")


def start_scheduler(bot: commands.Bot) -> None:
    if scheduler.running:
        return

    async def cleanup_job() -> None:
        try:
            await run_order_cleanup(bot)
        except Exception:
            LOGGER.exception("order_cleanup a échoué")

    scheduler.add_job(cleanup_job, "interval", minutes=15, id="order_cleanup", replace_existing=True)
    scheduler.start()
    LOGGER.info("Scheduler démarré (cleanup ordres/quêtes toutes les 15 min)")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
