"""Lecture fame Albion (PvE / gathering) pour les ordres auto."""

from __future__ import annotations

from typing import Any

from bot.services.albion_api import AlbionAPIClient, AlbionAPIError


def extract_fame(data: dict[str, Any] | None, kind: str) -> int:
    if not data:
        return 0
    stats = data.get("LifetimeStatistics") or {}
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


async def fetch_member_fame(api: AlbionAPIClient, *, player_id: str | None, name: str | None, kind: str) -> tuple[int, str | None]:
    """Retourne (fame, player_id éventuellement découvert)."""

    data: dict[str, Any] | None = None
    found_id = player_id
    try:
        if player_id:
            data = await api.get_player(player_id)
        elif name:
            search = await api.search_players(name)
            players = (search.get("players") if isinstance(search, dict) else None) or []
            if not players:
                return 0, found_id
            first = players[0]
            found_id = str(first.get("Id") or "") or None
            if found_id:
                data = await api.get_player(found_id)
            else:
                data = first if isinstance(first, dict) else None
    except AlbionAPIError:
        return 0, found_id
    return extract_fame(data if isinstance(data, dict) else None, kind), found_id
