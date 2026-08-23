"""Vérifications de permissions basées sur les rôles Discord."""

from __future__ import annotations

import discord

from bot.config import ADMIN_ROLE_KEYS, OFFICER_ROLE_KEYS, ORDER_MANAGER_ROLE_KEYS, ROLE_NAMES


def _member_role_names(member: discord.Member) -> set[str]:
    return {role.name for role in member.roles}


def has_any_role(member: discord.Member, role_keys: tuple[str, ...] | list[str] | set[str]) -> bool:
    """Vérifie si un membre possède au moins un rôle configuré."""

    names = _member_role_names(member)
    expected = {ROLE_NAMES[key] for key in role_keys if key in ROLE_NAMES}
    return bool(names & expected)


def is_guild_master(member: discord.Member) -> bool:
    return has_any_role(member, ADMIN_ROLE_KEYS)


def can_manage_orders(member: discord.Member) -> bool:
    return is_guild_master(member) or has_any_role(member, ORDER_MANAGER_ROLE_KEYS)


def is_officer(member: discord.Member) -> bool:
    return has_any_role(member, OFFICER_ROLE_KEYS)


def can_manage_treasury(member: discord.Member) -> bool:
    return is_guild_master(member) or has_any_role(member, ("grand_treasurer",))


def _normalize_label(value: str) -> str:
    """Normalise un nom de salon/rôle (emoji, espaces, casse)."""

    cleaned = "".join(ch for ch in value.lower() if ch.isalnum() or ch in {"-", "_", " "})
    return cleaned.replace("_", "-").replace(" ", "-").strip("-")


def role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    exact = discord.utils.get(guild.roles, name=role_name)
    if exact is not None:
        return exact
    target = _normalize_label(role_name)
    for role in guild.roles:
        if _normalize_label(role.name) == target or target in _normalize_label(role.name):
            return role
    return None


def channel_by_name(guild: discord.Guild, channel_name: str) -> discord.TextChannel | None:
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if isinstance(channel, discord.TextChannel):
        return channel
    target = _normalize_label(channel_name)
    for text_channel in guild.text_channels:
        if _normalize_label(text_channel.name) == target or target in _normalize_label(text_channel.name):
            return text_channel
    return None


def find_role(guild: discord.Guild, key: str) -> discord.Role | None:
    return role_by_name(guild, ROLE_NAMES.get(key, key))


def find_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    from bot.config import CHANNEL_NAMES

    return channel_by_name(guild, CHANNEL_NAMES.get(key, key))
