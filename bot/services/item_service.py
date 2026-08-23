"""Services utilitaires pour items Albion (icônes, noms, craft futur)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from bot.config import CACHE_TTL_SECONDS, settings
from bot.utils.cache import cached


class ItemServiceError(RuntimeError):
    """Erreur liée aux données d'items."""


class ItemService:
    """Client albion.tools et helpers items.

    Phase 1 fournit les primitives. Les calculs /craft_profit seront enrichis
    en Phase 6 selon les endpoints disponibles et le format souhaité.
    """

    def __init__(self, base_url: str | None = None, *, timeout: float = 15.0) -> None:
        self.base_url = (base_url or settings.albion_tools_base_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Albion-PPCF-Bot/1.0"})

    async def close(self) -> None:
        await self._client.aclose()

    @cached(ttl=CACHE_TTL_SECONDS["item_icons"])
    async def get_icon_url(self, item_id: str, *, size: int = 128) -> str:
        """Construit une URL d'icône stable pour embeds Discord.

        L'API Render d'Albion est publique et utilisée couramment par les bots.
        """

        encoded = quote(item_id)
        return f"https://render.albiononline.com/v1/item/{encoded}.png?size={size}"

    @cached(ttl=CACHE_TTL_SECONDS["item_icons"])
    async def normalize_item_name(self, item_name: str) -> str:
        """Normalisation minimale avant ajout d'une vraie base d'items."""

        return " ".join(item_name.strip().split())

    async def get_craft_profit_placeholder(self, item_id: str) -> dict[str, Any]:
        """Point d'extension pour /craft_profit en Phase 6."""

        raise ItemServiceError(f"Calcul craft_profit non implémenté en Phase 1 pour {item_id}")
