"""Service container shared by the API process and the worker process."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services.cache import ProductCache, QuotaService, RateLimiter
from app.services.extraction.base import VisionExtractor
from app.services.scoring import AdditiveTable
from app.services.storage import ImageStore


class JobQueue(Protocol):
    async def enqueue_scan(self, scan_id: uuid.UUID) -> None: ...


class ArqQueue:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def enqueue_scan(self, scan_id: uuid.UUID) -> None:
        # _job_id makes enqueueing idempotent: the same scan is never queued twice.
        await self.pool.enqueue_job("process_scan_job", str(scan_id), _job_id=f"scan:{scan_id}")


class InlineQueue:
    """Runs jobs as background tasks in-process. For tests and single-process local dev."""

    def __init__(self, runner: Callable[[uuid.UUID], Coroutine[Any, Any, None]]) -> None:
        self.runner = runner
        self.tasks: set[asyncio.Task[None]] = set()

    async def enqueue_scan(self, scan_id: uuid.UUID) -> None:
        task = asyncio.create_task(self.runner(scan_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def drain(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


@dataclass
class Services:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    store: ImageStore
    extractor: VisionExtractor
    additives: AdditiveTable
    queue: JobQueue | None = None
    cache: ProductCache = field(init=False)
    limiter: RateLimiter = field(init=False)
    quotas: QuotaService = field(init=False)

    def __post_init__(self) -> None:
        self.cache = ProductCache(self.redis)
        self.limiter = RateLimiter(self.redis)
        self.quotas = QuotaService(self.redis)
