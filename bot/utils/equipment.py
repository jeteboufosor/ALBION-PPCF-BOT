"""Helpers équipement Albion : portrait render, icônes d'items, libellés.

Partagé entre l'onboarding (fiche profil) et le killboard (#champ-de-bataille).
Les URLs utilisent l'API Render officielle, déjà documentée dans le README.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

# Ordre des slots attendu par l'API Render pour le portrait équipé.
CHARACTER_SLOTS = ("MainHand", "OffHand", "Head", "Armor", "Shoes", "Bag", "Cape", "Mount", "Potion", "Food")

# (emoji, libellé FR, couleurs de zone) par KillArea remonté par l'API gameinfo.
ZONE_AREAS: dict[str, tuple[str, str, str | None]] = {
    "OPEN_WORLD": ("🌍", "Monde ouvert", "🟥⬛ rouge / noire"),
    "MISTS": ("🌫️", "Mists", "léthal"),
    "CORRUPTED_DUNGEON": ("🟧", "Donjon corrompu", "léthal"),
    "HELLGATE": ("🔥", "Hellgate", "léthal"),
    "HELLGATE_2V2": ("🔥", "Hellgate 2v2", "léthal"),
    "HELLGATE_5V5": ("🔥", "Hellgate 5v5", "léthal"),
    "HELLGATE_10V10": ("🔥", "Hellgate 10v10", "léthal"),
    "AVALON": ("🛤️", "Routes d'Avalon", "léthal"),
    "ARENA": ("⚔️", "Arène", "non-léthal"),
    "CRYSTAL_ARENA": ("⚔️", "Arène de cristal", "non-léthal"),
    "EXPEDITION": ("🗺️", "Expédition", "non-léthal"),
    "DUNGEON": ("🕳️", "Donjon", None),
    "DUNGEON_SOLO": ("🕳️", "Donjon solo", None),
    "DUNGEON_GROUP": ("🕳️", "Donjon groupe", None),
}


def equip_token(item: dict[str, Any] | None) -> str:
    """Token d'un item pour l'URL du portrait : ``Type@enchant?quality``.

    Gère les deux formats de l'API : enchant inclus dans ``Type`` (``T4_MAIN_SWORD@2``,
    kills/morts) ou champ ``EnchantmentLevel`` séparé (profil joueur).
    """

    if not item:
        return ""
    raw = item.get("Type") or item.get("TypeName") or ""
    if not raw:
        return ""
    base = raw.split("?")[0]
    enchant = int(item.get("EnchantmentLevel") or 0)
    if enchant == 0 and "@" in base:
        token = base.split("@", 1)[1]
        enchant = int(token) if token.isdigit() else 0
    base = base.split("@")[0]
    quality = int(item.get("Quality") or 1)
    if enchant:
        return f"{base}@{enchant}?{quality}"
    return f"{base}?{quality}"


def character_render_url(equipment: dict[str, Any] | None, *, size: int = 512) -> str | None:
    """Portrait équipé via l'API Render officielle."""

    if not equipment:
        return None
    parts = [
        equip_token(equipment.get(slot) if isinstance(equipment.get(slot), dict) else None)
        for slot in CHARACTER_SLOTS
    ]
    if not any(parts):
        return None
    code = "|".join(parts)
    return f"https://render.albiononline.com/v1/character/{quote(code, safe='@?|_')}.png?size={size}"


def strip_item_affixes(item_type: str) -> str:
    """Retire l'enchant (@N) et la qualité (?N) d'un Type d'item."""

    return (item_type or "").split("@")[0].split("?")[0]


def item_enchant_level(item_type: str) -> int:
    """Niveau d'enchantement (0 si absent) d'un Type d'item."""

    raw = (item_type or "").strip()
    if "@" not in raw:
        return 0
    token = raw.split("@", 1)[1].split("?")[0]
    return int(token) if token.isdigit() else 0


def item_icon_url(item_type: str | None, *, size: int = 128) -> str | None:
    """URL de l'icône d'un item (sans enchant pour matcher le catalogue)."""

    if not item_type:
        return None
    base = strip_item_affixes(item_type)
    if not base:
        return None
    return f"https://render.albiononline.com/v1/item/{quote(base, safe='_')}.png?size={size}"


def zone_line(event: dict[str, Any]) -> str:
    """Ligne « Zone » lisible pour un évènement killboard.

    L'API gameinfo renvoie ``Location`` à ``null`` pour les kills : on se rabat
    sur ``KillArea`` (type de zone) et on l'habille (couleur rouge/noire/orange…).
    """

    location = (event.get("Location") or "").strip()
    if location:
        return f"🗺️ Zone : {location}"

    area = (event.get("KillArea") or "").strip().upper()
    emoji, label, colors = ZONE_AREAS.get(area, ("", None, None))
    if label is None:
        raw = event.get("KillArea") or event.get("Category") or "—"
        return f"🗺️ Zone : {raw}"
    suffix = f" · {colors}" if colors else ""
    return f"🗺️ Zone : {emoji} {label}{suffix}"
