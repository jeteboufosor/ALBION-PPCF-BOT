"""Planificateur APScheduler (tâches récurrentes)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from bot.tasks.deployment_reminder import run_deployment_reminders
from bot.tasks.order_cleanup import run_order_cleanup
from bot.tasks.ticket_cleanup import run_ticket_cleanup

LOGGER = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Berlin")


def start_scheduler(bot: commands.Bot) -> None:
    if scheduler.running:
        return

    async def deadline_job() -> None:
        try:
            from bot.cogs.orders import expire_overdue_orders

            closed = await expire_overdue_orders(bot)
            if closed:
                LOGGER.info("%s ordre(s) clôturé(s) par deadline", closed)
        except Exception:
            LOGGER.exception("expire_overdue_orders a échoué")

    async def cleanup_job() -> None:
        try:
            await run_order_cleanup(bot)
        except Exception:
            LOGGER.exception("order_cleanup a échoué")

    async def ticket_job() -> None:
        try:
            await run_ticket_cleanup(bot)
        except Exception:
            LOGGER.exception("ticket_cleanup a échoué")

    scheduler.add_job(deadline_job, "interval", minutes=1, id="order_deadline", replace_existing=True)
    scheduler.add_job(cleanup_job, "interval", minutes=15, id="order_cleanup", replace_existing=True)
    scheduler.add_job(ticket_job, "interval", hours=6, id="ticket_cleanup", replace_existing=True)
    scheduler.start()
    LOGGER.info("Scheduler démarré (deadline 1 min, archive 15 min, tickets 6 h)")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
