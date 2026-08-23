"""Planificateur APScheduler (tâches récurrentes)."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from bot.tasks.daily_backup import run_daily_backup
from bot.tasks.deployment_reminder import run_deployment_reminders
from bot.tasks.killboard_sync import run_killboard_sync
from bot.tasks.monthly_reset import run_monthly_reset
from bot.tasks.order_cleanup import run_order_cleanup
from bot.tasks.ticket_cleanup import run_ticket_cleanup
from bot.tasks.weekly_health import run_weekly_health

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

    async def deploy_job() -> None:
        await run_deployment_reminders(bot)

    async def killboard_job() -> None:
        await run_killboard_sync(bot)

    scheduler.add_job(deadline_job, "interval", minutes=1, id="order_deadline", replace_existing=True)
    scheduler.add_job(deploy_job, "interval", minutes=1, id="deploy_reminder", replace_existing=True)
    scheduler.add_job(killboard_job, "interval", minutes=5, id="killboard_sync", replace_existing=True)
    scheduler.add_job(cleanup_job, "interval", minutes=15, id="order_cleanup", replace_existing=True)
    scheduler.add_job(ticket_job, "interval", hours=6, id="ticket_cleanup", replace_existing=True)
    scheduler.start()
    LOGGER.info("Scheduler: deadline/deploy 1 min, killboard 5 min, archive 15 min")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
