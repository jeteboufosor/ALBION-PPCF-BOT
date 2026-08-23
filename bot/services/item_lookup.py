"""Résolution d'items Albion depuis un nom français / anglais / ID."""

from __future__ import annotations

import re
import unicodedata

# Mot-clé FR/EN -> unique uniqueName (sans tier).
_BASE: dict[str, str] = {
    "bois": "WOOD",
    "wood": "WOOD",
    "planche": "PLANKS",
    "planks": "PLANKS",
    "minerai": "ORE",
    "ore": "ORE",
    "lingot": "METALBAR",
    "bar": "METALBAR",
    "metal": "METALBAR",
    "pierre": "ROCK",
    "rock": "ROCK",
    "stone": "ROCK",
    "bloc": "STONEBLOCK",
    "cuir": "HIDE",
    "hide": "HIDE",
    "peau": "HIDE",
    "leather": "LEATHER",
    "fibre": "FIBER",
    "fiber": "FIBER",
    "coton": "FIBER",
    "tissu": "CLOTH",
    "cloth": "CLOTH",
    "laine": "CLOTH",
}

_TIER_WORDS = {
    "t2": 2, "t3": 3, "t4": 4, "t5": 5, "t6": 6, "t7": 7, "t8": 8,
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
}


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def resolve_item_query(raw: str) -> list[tuple[str, str]]:
    """Retourne une liste (unique_id, label) triée, max 25."""

    text = _fold(raw.strip())
    if not text:
        return _default_suggestions()
    compact = text.replace(" ", "").replace("-", "_")
    if re.fullmatch(r"t[2-8]_[a-z0-9_]+", compact) or re.fullmatch(r"[a-z0-9_]+", compact) and "_" in compact and compact[0] == "t":
        return [(compact.upper(), compact.upper())]

    tier = None
    m = re.search(r"\bt([2-8])\b", text)
    if m:
        tier = int(m.group(1))
    else:
        for token in text.replace("_", " ").split():
            if token in _TIER_WORDS and token.startswith("t"):
                tier = _TIER_WORDS[token]
                break

    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in _TIER_WORDS]
    base = None
    for w in words:
        if w in _BASE:
            base = _BASE[w]
            break
    if base is None:
        for key, val in _BASE.items():
            if key in text:
                base = val
                break

    if base is None:
        # ID brut
        guess = compact.upper()
        return [(guess, guess)]

    tiers = [tier] if tier else [4, 5, 6, 7, 8]
    out: list[tuple[str, str]] = []
    fr = next((k for k, v in _BASE.items() if v == base and k not in {"wood", "ore", "rock", "hide", "fiber", "planks", "cloth"}), base.lower())
    for t in tiers:
        uid = f"T{t}_{base}"
        out.append((uid, f"{fr} T{t}  ({uid})"))
    return out[:25]


def _default_suggestions() -> list[tuple[str, str]]:
    items = []
    for t in (4, 5, 6, 7, 8):
        items.append((f"T{t}_WOOD", f"bois T{t}"))
    items.append(("T6_ORE", "minerai T6"))
    items.append(("T6_HIDE", "cuir T6"))
    items.append(("T6_FIBER", "fibre T6"))
    items.append(("T6_ROCK", "pierre T6"))
    return items


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


async def item_autocomplete(interaction: "discord.Interaction", current: str):
    from discord import app_commands

    choices = resolve_item_query(current or "bois")
    return [app_commands.Choice(name=label[:100], value=uid) for uid, label in choices[:25]]
