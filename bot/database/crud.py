"""Fonctions CRUD communes.

Les cogs des prochaines phases utiliseront ces helpers pour éviter de répéter
les requêtes simples. Les opérations métier complexes resteront dans les cogs
ou services dédiés.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ContributionScore, Member, Order, Ticket, TreasuryState, utcnow


async def get_member_by_discord_id(session: AsyncSession, discord_id: int) -> Member | None:
    result = await session.execute(select(Member).where(Member.discord_id == discord_id))
    return result.scalar_one_or_none()


async def get_or_create_member(session: AsyncSession, *, discord_id: int, discord_name: str) -> Member:
    member = await get_member_by_discord_id(session, discord_id)
    if member is not None:
        member.discord_name = discord_name
        member.last_active_at = utcnow()
        return member

    member = Member(discord_id=discord_id, discord_name=discord_name, last_active_at=utcnow())
    session.add(member)
    await session.flush()

    session.add(ContributionScore(member_id=member.id, monthly_period=utcnow().strftime("%Y-%m")))
    return member


async def get_treasury_state(session: AsyncSession) -> TreasuryState:
    state = await session.get(TreasuryState, 1)
    if state is None:
        state = TreasuryState(id=1)
        session.add(state)
        await session.flush()
    return state


async def next_order_number(session: AsyncSession) -> int:
    result = await session.execute(select(func.coalesce(func.max(Order.order_number), 0) + 1))
    return int(result.scalar_one())


async def next_ticket_number(session: AsyncSession) -> int:
    result = await session.execute(select(func.coalesce(func.max(Ticket.ticket_number), 0) + 1))
    return int(result.scalar_one())


async def list_top_scores(
    session: AsyncSession,
    column: str,
    *,
    limit: int = 10,
) -> list[tuple[Member, ContributionScore]]:
    """Retourne un classement simple membre + score.

    column accepté: order_points_all_time, order_points_monthly,
    total_silver_donated, total_fame.
    """

    if column not in {
        "order_points_all_time",
        "order_points_monthly",
        "total_silver_donated",
        "silver_donated_monthly",
        "total_fame",
        "fame_monthly",
    }:
        raise ValueError(f"Colonne leaderboard invalide: {column}")

    score_column = getattr(ContributionScore, column)
    stmt: Select[tuple[Member, ContributionScore]] = (
        select(Member, ContributionScore)
        .join(ContributionScore, ContributionScore.member_id == Member.id)
        .order_by(score_column.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.all())
