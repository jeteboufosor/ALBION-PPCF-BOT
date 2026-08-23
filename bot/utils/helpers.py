"""Petits helpers génériques."""

from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(UTC)


def truncate(text: str, max_length: int = 1024) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def parse_int(value: str) -> int:
    """Parse un entier tolérant les espaces et suffixes simples k/m."""

    clean = value.strip().lower().replace(" ", "").replace("_", "")
    multiplier = 1
    if clean.endswith("k"):
        multiplier = 1_000
        clean = clean[:-1]
    elif clean.endswith("m"):
        multiplier = 1_000_000
        clean = clean[:-1]
    return int(float(clean) * multiplier)
