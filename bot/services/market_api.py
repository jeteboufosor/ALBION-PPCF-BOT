"""Client async pour albion-online-data.com."""

from __future__ import annotations

from typing import Any

import httpx

from bot.config import CACHE_TTL_SECONDS, settings
from bot.utils.cache import cached

FORT_STERLING = "Fort Sterling"
ALBION_CITIES = ("Fort Sterling", "Bridgewatch", "Lymhurst", "Martlock", "Thetford", "Caerleon", "Black Market")


class MarketAPIError(RuntimeError):
    """Erreur d'appel API marché."""


class MarketAPIClient:
    """Client pour les prix et historiques Albion Data Project."""

    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or settings.albion_market_base_url).rstrip("/")
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
            raise MarketAPIError(f"Erreur API marché pour {url}: {exc}") from exc

    @cached(ttl=CACHE_TTL_SECONDS["market_prices"])
    async def get_prices(self, item_ids: str | list[str], *, locations: str | list[str] = FORT_STERLING) -> list[dict[str, Any]]:
        """Prix actuels pour un ou plusieurs items."""

        items = ",".join(item_ids) if isinstance(item_ids, list) else item_ids
        locs = ",".join(locations) if isinstance(locations, list) else locations
        return await self._get(f"prices/{items}", locations=locs)

    @cached(ttl=CACHE_TTL_SECONDS["market_prices"])
    async def compare_cities(self, item_id: str) -> list[dict[str, Any]]:
        """Prix dans les villes principales."""

        return await self.get_prices(item_id, locations=list(ALBION_CITIES))

    @cached(ttl=CACHE_TTL_SECONDS["market_prices"])
    async def get_history(
        self,
        item_id: str,
        *,
        location: str = FORT_STERLING,
        date: str | None = None,
        qualities: str | None = None,
    ) -> list[dict[str, Any]]:
        """Historique de prix. date peut être au format attendu par l'API."""

        return await self._get(f"history/{item_id}", locations=location, date=date, qualities=qualities)
