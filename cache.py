"""Answer cache keyed on the redacted question, patient context and provider.

Only redacted text ever reaches a cache key. Answers involving an emergency
are never served from cache, so triage always runs fresh.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol


def cache_key(question: str, context: dict[str, Any], provider: str) -> str:
    payload = json.dumps({"q": question.strip().lower(), "c": context, "p": provider}, sort_keys=True, default=str)
    return "carina:answer:" + hashlib.sha256(payload.encode()).hexdigest()


class AnswerCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def set(self, key: str, value: dict[str, Any]) -> None: ...

    @property
    def backend(self) -> str: ...


class MemoryCache:
    def __init__(self, ttl_s: int = 3600, max_items: int = 2048) -> None:
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def backend(self) -> str:
        return "memory"

    async def get(self, key: str) -> dict[str, Any] | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() > expires:
            self._items.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: dict[str, Any]) -> None:
        if len(self._items) >= self.max_items:
            oldest = min(self._items.items(), key=lambda kv: kv[1][0])[0]
            self._items.pop(oldest, None)
        self._items[key] = (time.monotonic() + self.ttl_s, value)


class RedisCache:
    def __init__(self, url: str, ttl_s: int = 3600) -> None:
        import redis.asyncio as redis  # optional dependency

        self.client = redis.from_url(url)
        self.ttl_s = ttl_s

    @property
    def backend(self) -> str:
        return "redis"

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self.client.get(key)
        except Exception:  # noqa: BLE001 - a cache outage must never fail a consultation
            return None
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        try:
            await self.client.set(key, json.dumps(value), ex=self.ttl_s)
        except Exception:  # noqa: BLE001
            return None


def build_cache(backend: str, redis_url: str, ttl_s: int) -> AnswerCache:
    if backend == "redis":
        return RedisCache(redis_url, ttl_s)
    return MemoryCache(ttl_s)
