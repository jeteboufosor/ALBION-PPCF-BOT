"""Lecture fame Albion (PvE / gathering) pour les ordres auto."""

from __future__ import annotations

import logging
from typing import Any

from bot.services.albion_api import AlbionAPIClient, AlbionAPIError

LOGGER = logging.getLogger(__name__)


def extract_fame(data: dict[str, Any] | None, kind: str) -> int | None:
    if not data or not isinstance(data, dict):
        return None
    stats = data.get("LifetimeStatistics")
    if not isinstance(stats, dict):
        if "KillFame" in data:
            return int(data.get("KillFame") or 0)
        return None

    if kind == "gathering_fame":
        gathering = stats.get("Gathering") or {}
        all_g = gathering.get("All") if isinstance(gathering, dict) else None
        if isinstance(all_g, dict):
            return int(all_g.get("Total") or all_g.get("total") or 0)
        total = 0
        if isinstance(gathering, dict):
            for node in gathering.values():
                if isinstance(node, dict):
                    total += int(node.get("Total") or node.get("total") or 0)
                elif isinstance(node, (int, float)):
                    total += int(node)
        return total

    # pve_fame par défaut
    pve = stats.get("PvE") or {}
    if isinstance(pve, dict):
        return int(pve.get("Total") or pve.get("total") or 0)
    return int(data.get("KillFame") or 0)


async def fetch_member_fame(
    api: AlbionAPIClient,
    *,
    player_id: str | None,
    name: str | None,
    kind: str,
) -> tuple[int | None, str | None]:
    """Retourne (fame, player_id éventuellement découvert).

    Retourne None pour la fame si l'API échoue ou si le joueur est introuvable,
    évitant d'écraser la progression ou de fixer une baseline erronée à 0.
    """

    if not player_id and not name:
        return None, None

    data: dict[str, Any] | None = None
    found_id = player_id
    try:
        if player_id:
            data = await api.get_player(player_id)
        elif name:
            cleaned = name.strip()
            search = await api.search_players(cleaned)
            players = (search.get("players") if isinstance(search, dict) else None) or []
            if not players:
                return None, found_id
            target = cleaned.lower()
            match = next((p for p in players if isinstance(p, dict) and str(p.get("Name", "")).lower() == target), None)
            if match is None:
                match = players[0] if isinstance(players[0], dict) else None
            if not match:
                return None, found_id
            found_id = str(match.get("Id") or "") or None
            if found_id:
                data = await api.get_player(found_id)
            else:
                data = match
    except AlbionAPIError as exc:
        LOGGER.debug("Erreur API Albion lors de fetch_member_fame (%s / %s): %s", player_id, name, exc)
        return None, found_id
    except Exception as exc:
        LOGGER.warning("Erreur inattendue dans fetch_member_fame (%s / %s): %s", player_id, name, exc)
        return None, found_id

    fame = extract_fame(data if isinstance(data, dict) else None, kind)
    return fame, found_id
