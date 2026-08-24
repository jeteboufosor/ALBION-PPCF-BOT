"""Vérifications de permissions basées sur les rôles Discord."""

from __future__ import annotations

import unicodedata

import discord

from bot.config import ADMIN_ROLE_KEYS, CHANNEL_NAMES, OFFICER_ROLE_KEYS, ORDER_MANAGER_ROLE_KEYS, ROLE_NAMES

# Mots-clés : retrouve un salon malgré emoji / faute (ex: trésorie).
CHANNEL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "treasury": ("tresor", "treasury", "banque"),
    "history": ("histor",),
    "declaration": ("declar",),
    "rules": ("regle", "rules"),
    "new_guide": ("guide",),
    "roles": ("role",),
    "priority_orders": ("ordre-prio", "ordreprio", "prioritaire"),
    "past_orders": ("ordres-pass", "ordrespass"),
    "ticket_logs": ("logs-ticket", "logsticket"),
    "quests": ("quete", "quest"),
    "arrival_departure": ("arriv",),
    "deployment": ("deploi", "deploy"),
    "promotion": ("promo",),
    "battlefield": ("champ", "bataille", "killboard", "kill"),
    "market_commands": ("marche", "market", "commandes-marche"),
    "leaderboard": ("leaderboard", "classement", "classem", "palmares", "top10"),
    "sql_backup": ("backup",),
    "bot_alerts": ("alertes-bot", "alerte-bot", "alertesbot"),
    "price_alerts": ("alertes-prix", "alerte-prix", "alertesprix"),
}


def _member_role_names(member: discord.Member) -> set[str]:
    return {role.name for role in member.roles}


def has_any_role(member: discord.Member, role_keys: tuple[str, ...] | list[str] | set[str]) -> bool:
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


def _fold(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    cleaned = "".join(ch.lower() if ch.isalnum() or ch in {"-", "_"} else "-" for ch in ascii_only)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _normalize_label(value: str) -> str:
    return _fold(value)


def role_by_name(guild: discord.Guild, role_name: str) -> discord.Role | None:
    exact = discord.utils.get(guild.roles, name=role_name)
    if exact is not None:
        return exact
    target = _fold(role_name)
    for role in guild.roles:
        folded = _fold(role.name)
        if folded == target or target in folded or folded in target:
            return role
    return None


def channel_by_name(guild: discord.Guild, channel_name: str) -> discord.TextChannel | None:
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if isinstance(channel, discord.TextChannel):
        return channel
    target = _fold(channel_name)
    for text_channel in guild.text_channels:
        folded = _fold(text_channel.name)
        if folded == target or target in folded or folded in target:
            return text_channel
    return None


def find_role(guild: discord.Guild, key: str) -> discord.Role | None:
    return role_by_name(guild, ROLE_NAMES.get(key, key))


def find_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    official = CHANNEL_NAMES.get(key, key)
    found = channel_by_name(guild, official)
    if found is not None:
        return found
    found = channel_by_name(guild, key)
    if found is not None:
        return found
    for keyword in CHANNEL_KEYWORDS.get(key, ()):
        for text_channel in guild.text_channels:
            if keyword in _fold(text_channel.name):
                return text_channel
    return None
