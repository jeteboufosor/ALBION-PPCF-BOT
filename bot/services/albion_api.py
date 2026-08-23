"""Client async pour l'API officielle Albion Online."""

from __future__ import annotations

from typing import Any

import httpx

from bot.config import CACHE_TTL_SECONDS, settings
from bot.utils.cache import cached


class AlbionAPIError(RuntimeError):
    """Erreur d'appel API Albion."""


class AlbionAPIClient:
    """Client léger gameinfo.albiononline.com."""

    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or settings.albion_api_base_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Albion-PPCF-Bot/1.0"})

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = await self._client.get(url, params={k: v for k, v in params.items() if v is not None})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise AlbionAPIError(f"Erreur API Albion pour {url}: {exc}") from exc

    @cached(ttl=CACHE_TTL_SECONDS["player_info"])
    async def search_players(self, query: str) -> dict[str, Any]:
        """Recherche de joueurs par pseudo."""

        return await self._get("search", q=query)

    @cached(ttl=CACHE_TTL_SECONDS["player_info"])
    async def get_player(self, player_id: str) -> dict[str, Any]:
        """Détails d'un joueur."""

        return await self._get(f"players/{player_id}")

    @cached(ttl=CACHE_TTL_SECONDS["player_info"])
    async def get_player_statistics(self, player_id: str) -> dict[str, Any]:
        """Statistiques fame détaillées d'un joueur."""

        return await self._get(f"players/{player_id}/statistics")

    @cached(ttl=CACHE_TTL_SECONDS["recent_kills"])
    async def get_player_kills(self, player_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return await self._get(f"players/{player_id}/kills", limit=limit)

    @cached(ttl=CACHE_TTL_SECONDS["recent_kills"])
    async def get_player_deaths(self, player_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        return await self._get(f"players/{player_id}/deaths", limit=limit)

    @cached(ttl=CACHE_TTL_SECONDS["player_info"])
    async def get_guild_members(self, guild_id: str | None = None) -> list[dict[str, Any]]:
        """Membres de la guilde Albion."""

        target_guild_id = guild_id or settings.albion_guild_id
        return await self._get(f"guilds/{target_guild_id}/members")

    @cached(ttl=CACHE_TTL_SECONDS["recent_kills"])
    async def get_recent_events(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Évènements killboard récents."""

        return await self._get("events", limit=limit, offset=offset)
