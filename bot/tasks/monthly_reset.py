"""Reset des points d'ordres mensuels le 1er du mois."""

from __future__ import annotations

import logging

from discord.ext import commands
from sqlalchemy import update

from bot.database.engine import session_scope
from bot.database.models import ContributionScore, utcnow

LOGGER = logging.getLogger(__name__)


async def run_monthly_reset(bot: commands.Bot) -> None:
    period = utcnow().strftime("%Y-%m")
    async with session_scope() as session:
        await session.execute(
            update(ContributionScore).values(order_points_monthly=0, monthly_period=period)
        )
    LOGGER.info("Reset leaderboard mensuel %s", period)
    cog = bot.get_cog("Leaderboard")
    if cog:
        for guild in bot.guilds:
            try:
                await cog.post_or_update(guild)  # type: ignore[attr-defined]
            except Exception:
                LOGGER.exception("Refresh leaderboard après reset")
