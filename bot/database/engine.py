"""Moteur SQLAlchemy async avec détection SQLite locale / PostgreSQL Railway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.config import DATA_DIR, settings
from bot.database.models import Base


def normalize_database_url(raw_url: str | None = None) -> str:
    """Retourne une URL compatible SQLAlchemy async.

    - Sans DATABASE_URL: SQLite local via aiosqlite.
    - Railway fournit souvent postgresql://: conversion vers postgresql+asyncpg://.
    """

    url = (raw_url if raw_url is not None else settings.database_url).strip()
    if not url:
        sqlite_path = Path(settings.sqlite_path)
        if not sqlite_path.is_absolute():
            sqlite_path = DATA_DIR.parent / sqlite_path
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{sqlite_path}"

    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


DATABASE_URL = normalize_database_url()
IS_POSTGRES = DATABASE_URL.startswith("postgresql+asyncpg://")
IS_SQLITE = DATABASE_URL.startswith("sqlite+aiosqlite://")

_engine_kwargs: dict[str, Any] = {
    "echo": False,
    "pool_pre_ping": True,
}

if IS_SQLITE:
    # SQLite ne supporte pas les mêmes options de pooling que PostgreSQL.
    _engine_kwargs.pop("pool_pre_ping", None)
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine: AsyncEngine = create_async_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _add_missing_order_columns(conn) -> None:
    """Ajoute les colonnes d'audit si la table orders existait déjà."""

    statements = (
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_by_discord_id BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_by_discord_id BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS close_reason VARCHAR(40)",
        "ALTER TABLE resource_requests ADD COLUMN IF NOT EXISTS original_quantity INTEGER",
        "ALTER TABLE deployment_responses ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ",
        "ALTER TABLE contribution_scores ADD COLUMN IF NOT EXISTS silver_donated_monthly INTEGER DEFAULT 0",
        "ALTER TABLE contribution_scores ADD COLUMN IF NOT EXISTS fame_monthly INTEGER DEFAULT 0",
        "ALTER TABLE contribution_scores ADD COLUMN IF NOT EXISTS fame_baseline INTEGER DEFAULT 0",
        "ALTER TABLE order_participants ADD COLUMN IF NOT EXISTS baseline_fame INTEGER",
    )
    if IS_SQLITE:
        statements = (
            "ALTER TABLE orders ADD COLUMN cancelled_by_discord_id BIGINT",
            "ALTER TABLE orders ADD COLUMN completed_by_discord_id BIGINT",
            "ALTER TABLE orders ADD COLUMN close_reason VARCHAR(40)",
            "ALTER TABLE resource_requests ADD COLUMN original_quantity INTEGER",
            "ALTER TABLE deployment_responses ADD COLUMN reminded_at DATETIME",
            "ALTER TABLE contribution_scores ADD COLUMN silver_donated_monthly INTEGER DEFAULT 0",
            "ALTER TABLE contribution_scores ADD COLUMN fame_monthly INTEGER DEFAULT 0",
            "ALTER TABLE contribution_scores ADD COLUMN fame_baseline INTEGER DEFAULT 0",
            "ALTER TABLE order_participants ADD COLUMN baseline_fame INTEGER",
        )
    for stmt in statements:
        try:
            await conn.execute(text(stmt))
        except Exception:
            pass


async def init_db() -> None:
    """Crée les tables manquantes.

    Suffisant pour le développement local. En production, on pourra ajouter Alembic
    quand le schéma sera stabilisé.
    """

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_order_columns(conn)


async def dispose_engine() -> None:
    """Ferme proprement les connexions DB."""

    await engine.dispose()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Contexte transactionnel réutilisable pour les cogs et tâches."""

    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
