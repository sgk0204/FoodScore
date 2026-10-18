"""Redis-backed product cache, locks, rate limits and quotas (edge cases 38, 39, 41).

Failure policy when Redis is down (edge case 39):
- cache reads/writes: fail open (skip the cache, do the real work)
- rate limits: fall back to an in-process counter
- quotas: fail open, but the global budget alarm still fires from the database count
"""

from __future__ import annotations

import contextlib
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PRODUCT_TTL_S = 30 * 24 * 3600


class ProductCache:
    """barcode → scored result snapshot. Only high-confidence, non-user-edited results."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(barcode: str) -> str:
        return f"product:{barcode}"

    async def get(self, barcode: str) -> dict[str, Any] | None:
        try:
            raw = await self.redis.get(self._key(barcode))
        except RedisError:
            log.warning("cache_unavailable", op="get")
            return None
        return json.loads(raw) if raw else None

    async def set(self, barcode: str, snapshot: dict[str, Any]) -> None:
        try:
            await self.redis.set(self._key(barcode), json.dumps(snapshot), ex=PRODUCT_TTL_S)
        except RedisError:
            log.warning("cache_unavailable", op="set")

    async def delete(self, barcode: str) -> None:
        try:
            await self.redis.delete(self._key(barcode))
        except RedisError:
            log.warning("cache_unavailable", op="delete")


class BarcodeLock:
    """SET NX lock so two simultaneous first scans of a barcode make one LLM call (edge 41)."""

    def __init__(self, redis: Redis, barcode: str, ttl_s: int = 90) -> None:
        self.redis = redis
        self.key = f"lock:barcode:{barcode}"
        self.ttl_s = ttl_s
        self.token = str(time.time_ns())

    async def acquire(self) -> bool:
        try:
            return bool(await self.redis.set(self.key, self.token, nx=True, ex=self.ttl_s))
        except RedisError:
            return True  # fail open: worst case is a duplicate LLM call

    async def release(self) -> None:
        try:
            if (await self.redis.get(self.key)) in (self.token, self.token.encode()):
                await self.redis.delete(self.key)
        except RedisError:
            pass


class RateLimiter:
    """Fixed-window counter per key; in-memory fallback when Redis is unavailable."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._local: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    async def hit(self, key: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
        """Returns (allowed, retry_after_s)."""
        window = int(time.time() // window_s)
        rkey = f"rl:{key}:{window}"
        try:
            count = await self.redis.incr(rkey)
            if count == 1:
                await self.redis.expire(rkey, window_s)
        except RedisError:
            count, started = self._local[rkey]
            count += 1
            self._local[rkey] = (count, started or time.time())
        retry_after = window_s - int(time.time() % window_s)
        return count <= limit, retry_after


class QuotaService:
    """Daily new-scan quotas per user/guest plus a global daily budget (user story 6)."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).strftime("%Y%m%d")

    async def used(self, owner: str) -> int:
        try:
            raw = await self.redis.get(f"quota:{owner}:{self._day()}")
        except RedisError:
            return 0
        return int(raw or 0)

    async def consume(self, owner: str) -> int:
        try:
            key = f"quota:{owner}:{self._day()}"
            count = int(await self.redis.incr(key))
            if count == 1:
                await self.redis.expire(key, 26 * 3600)
            return count
        except RedisError:
            return 0

    async def refund(self, owner: str) -> None:
        with contextlib.suppress(RedisError):
            await self.redis.decr(f"quota:{owner}:{self._day()}")

    async def consume_global(self) -> int:
        return await self.consume("__global__")
