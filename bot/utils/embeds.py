"""Générateurs d'embeds Discord réutilisables."""

from __future__ import annotations

from datetime import datetime

import discord

ALBION_ORANGE = discord.Color.from_rgb(235, 126, 35)
ALBION_BLUE = discord.Color.from_rgb(68, 120, 190)
SUCCESS_GREEN = discord.Color.from_rgb(46, 204, 113)
WARNING_YELLOW = discord.Color.from_rgb(241, 196, 15)
ERROR_RED = discord.Color.from_rgb(231, 76, 60)


def base_embed(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = ALBION_ORANGE,
) -> discord.Embed:
    """Embed standard du bot."""

    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    embed.set_footer(text="Albion PPCF Bot • Fort Sterling")
    return embed


def success_embed(title: str, description: str | None = None) -> discord.Embed:
    return base_embed(title, description, color=SUCCESS_GREEN)


def error_embed(title: str, description: str | None = None) -> discord.Embed:
    return base_embed(title, description, color=ERROR_RED)


def warning_embed(title: str, description: str | None = None) -> discord.Embed:
    return base_embed(title, description, color=WARNING_YELLOW)


def info_embed(title: str, description: str | None = None) -> discord.Embed:
    return base_embed(title, description, color=ALBION_BLUE)


def discord_timestamp(value: datetime, style: str = "F") -> str:
    """Timestamp Discord (<t:unix:F> date, :R relatif)."""

    return f"<t:{int(value.timestamp())}:{style}>"


def progress_bar(current: int, target: int, *, width: int = 24) -> str:
    """Barre de progression texte adaptée aux embeds."""

    if target <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, current / target))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def format_silver(amount: int) -> str:
    """Formate un montant silver lisiblement."""

    return f"{amount:,}".replace(",", " ") + " silver"


def format_order_number(number: int) -> str:
    """Format visible #001."""

    return f"#{number:03d}"
