"""Résolution d'items Albion (FR / EN / ID) via le dump officiel."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    import discord

LOGGER = logging.getLogger(__name__)

ITEMS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json"

_catalog: list[tuple[str, str, str]] = []  # unique, fr, en
_loaded = False

_FALLBACK_BASE: dict[str, str] = {
    "bois": "WOOD",
    "wood": "WOOD",
    "planche": "PLANKS",
    "minerai": "ORE",
    "ore": "ORE",
    "lingot": "METALBAR",
    "pierre": "ROCK",
    "cuir": "HIDE",
    "hide": "HIDE",
    "fibre": "FIBER",
    "tissu": "CLOTH",
    "epee": "MAIN_SWORD",
    "sword": "MAIN_SWORD",
    "hache": "MAIN_AXE",
    "axe": "MAIN_AXE",
    "arc": "2H_BOW",
    "bow": "2H_BOW",
    "baton": "2H_NATURESTAFF",
    "casque": "HEAD_PLATE_SET1",
    "armure": "ARMOR_PLATE_SET1",
    "bottes": "SHOES_LEATHER_SET1",
}


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


async def ensure_catalog() -> None:
    global _catalog, _loaded
    if _loaded:
        return
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(ITEMS_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        LOGGER.exception("Impossible de charger le catalogue items")
        _loaded = True
        return
    catalog: list[tuple[str, str, str]] = []
    if isinstance(data, list):
        iterable = data
    elif isinstance(data, dict):
        iterable = data.values()
    else:
        iterable = []
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        uid = entry.get("UniqueName") or entry.get("uniqueName") or ""
        if not uid or uid.startswith("UNIQUE_HIDEOUT") or "@" in uid:
            continue
        loc = entry.get("LocalizedNames") or {}
        fr = loc.get("FR-FR") or loc.get("FR-CA") or ""
        en = loc.get("EN-US") or loc.get("EN-GB") or uid
        if not fr:
            fr = en
        catalog.append((uid, fr, en))
    _catalog = catalog
    _loaded = True
    LOGGER.info("Catalogue items chargé: %s entrées", len(_catalog))


def _search_catalog(query: str, *, limit: int = 25) -> list[tuple[str, str]]:
    q = _fold(query)
    scored: list[tuple[int, str, str]] = []
    for uid, fr, en in _catalog:
        fu, ff, fe = _fold(uid), _fold(fr), _fold(en)
        if q == fu or q == ff:
            score = 0
        elif ff.startswith(q) or fu.startswith(q):
            score = 1
        elif q in ff or q in fe or q in fu:
            score = 2
        else:
            continue
        label = f"{fr}  ({uid})" if fr else uid
        scored.append((score, uid, label))
    scored.sort(key=lambda x: (x[0], len(x[2])))
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for _, uid, label in scored:
        if uid in seen:
            continue
        seen.add(uid)
        out.append((uid, label[:100]))
        if len(out) >= limit:
            break
    return out


def _fallback(query: str) -> list[tuple[str, str]]:
    text = _fold(query)
    m = re.search(r"t([2-8])", text)
    tier = int(m.group(1)) if m else None
    base = None
    for key, val in _FALLBACK_BASE.items():
        if key in text:
            base = val
            break
    if base is None:
        guess = text.replace(" ", "_").upper()
        return [(guess, guess)] if guess else []
    tiers = [tier] if tier else [4, 5, 6, 7, 8]
    return [(f"T{t}_{base}", f"{query} T{t} (T{t}_{base})") for t in tiers]


async def resolve_item_query(raw: str) -> list[tuple[str, str]]:
    await ensure_catalog()
    text = (raw or "").strip()
    if _catalog:
        if not text:
            return _search_catalog("epee", limit=10) + _search_catalog("bois", limit=8)
        found = _search_catalog(text)
        if found:
            return found
    return _fallback(text)


async def item_autocomplete(interaction: "discord.Interaction", current: str):
    from discord import app_commands

    choices = await resolve_item_query(current)
    return [app_commands.Choice(name=label[:100], value=uid) for uid, label in choices[:25]]
