"""Cache mémoire TTL pour appels API async.

Usage:
    @cached(ttl=600)
    async def get_price(item_id: str): ...
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")


def _make_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Hashable:
    """Construit une clé de cache stable pour arguments simples."""

    frozen_kwargs = tuple(sorted(kwargs.items()))
    return args, frozen_kwargs


def cached(ttl: int) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Décorateur de cache TTL pour fonctions async.

    Le cache est volontairement en mémoire: simple, rapide, et suffisant pour
    les TTL API demandés. Il est réinitialisé à chaque redémarrage du bot.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        cache: dict[Hashable, tuple[float, R]] = {}
        locks: dict[Hashable, asyncio.Lock] = {}

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = _make_key(args, cast(dict[str, Any], kwargs))
            now = time.monotonic()
            cached_value = cache.get(key)
            if cached_value and cached_value[0] > now:
                return cached_value[1]

            lock = locks.setdefault(key, asyncio.Lock())
            async with lock:
                # Double vérification après attente du lock.
                cached_value = cache.get(key)
                now = time.monotonic()
                if cached_value and cached_value[0] > now:
                    return cached_value[1]

                result = await func(*args, **kwargs)
                cache[key] = (now + ttl, result)
                return result

        def cache_clear() -> None:
            cache.clear()
            locks.clear()

        setattr(wrapper, "cache_clear", cache_clear)
        return wrapper

    return decorator
