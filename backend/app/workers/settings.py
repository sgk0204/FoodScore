"""ARQ worker definition: ``arq app.workers.settings.WorkerSettings``.

Jobs are acknowledged only after they finish; a crashed worker's job is retried and the
reaper marks anything stuck in PROCESSING as FAILED (edge case 40).
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import urlparse

from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.workers.reaper import reap
from app.workers.scan_job import process_scan_job


def redis_settings(settings: Settings) -> RedisSettings:
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
        username=parsed.username,
        ssl=parsed.scheme == "rediss",
    )


async def startup(ctx: dict[str, Any]) -> None:
    from app.main import build_services

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment != "local")
    svc = await build_services(settings.model_copy(update={"job_mode": "inline"}))
    ctx["services"] = svc


async def shutdown(ctx: dict[str, Any]) -> None:
    svc = ctx.get("services")
    if svc is not None:
        await svc.redis.aclose()
        await svc.engine.dispose()


_settings = get_settings()


class WorkerSettings:
    functions: ClassVar = [process_scan_job]
    cron_jobs: ClassVar = [cron(reap, second=0, run_at_startup=True)]  # every minute
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings(_settings)
    max_jobs = 10
    job_timeout = 120
    max_tries = 2
    keep_result = 3600
