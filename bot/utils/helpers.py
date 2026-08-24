"""Petits helpers génériques."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_TS_RE = re.compile(r"<t:(\d+)(?::[tTdDfFR])?>")


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_discord_time(raw: str) -> datetime:
    """Parse `<t:1787511600:R>` ou un unix brut."""

    text = raw.strip()
    match = _TS_RE.search(text)
    if match:
        return datetime.fromtimestamp(int(match.group(1)), tz=UTC)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 10:
        return datetime.fromtimestamp(int(digits[:10]), tz=UTC)
    raise ValueError("Colle un timestamp Discord : `<t:1787511600:R>`")


def truncate(text: str, max_length: int = 1024) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def parse_int(value: str) -> int:
    clean = value.strip().lower().replace(" ", "").replace("_", "")
    multiplier = 1
    if clean.endswith("k"):
        multiplier = 1_000
        clean = clean[:-1]
    elif clean.endswith("m"):
        multiplier = 1_000_000
        clean = clean[:-1]
    return int(float(clean) * multiplier)
