"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.db.session import make_engine, make_sessionmaker
from app.services.context import ArqQueue, InlineQueue, Services
from app.services.extraction.fallback import build_extractor
from app.services.pipeline import process_scan
from app.services.scoring import DEFAULT_ADDITIVES_PATH, load_additive_table
from app.services.storage import build_store
from app.workers.reaper import run_forever as run_reaper_forever

log = structlog.get_logger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


async def build_services(settings: Settings) -> Services:
    engine = make_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    svc = Services(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        redis=redis,
        store=build_store(settings),
        extractor=build_extractor(settings),
        additives=load_additive_table(DEFAULT_ADDITIVES_PATH),
    )
    if settings.job_mode == "inline":
        svc.queue = InlineQueue(lambda scan_id: process_scan(svc, scan_id))
    else:
        from arq import create_pool

        from app.workers.settings import redis_settings

        svc.queue = ArqQueue(await create_pool(redis_settings(settings)))
    return svc


def _init_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.environment != "local")
    _init_sentry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = services or await build_services(settings)
        app.state.services = svc
        log.info("api_started", environment=settings.environment, provider=settings.llm_provider)
        reaper: asyncio.Task[None] | None = None
        if services is None and settings.job_mode == "inline":
            # No separate worker → no ARQ cron, so the API runs the reaper itself.
            reaper = asyncio.create_task(run_reaper_forever(svc))
        try:
            yield
        finally:
            if reaper is not None:
                reaper.cancel()
            if services is None:
                if isinstance(svc.queue, ArqQueue):
                    await svc.queue.pool.aclose()
                await svc.redis.aclose()
                await svc.engine.dispose()

    app = FastAPI(
        title="FoodScore API",
        version="1.0.0",
        description="AI-powered food label scanner that scores packaged food out of 100.",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 else f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms}"
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path not in ("/health", "/metrics"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-None-Match",
            "X-Request-ID",
        ],
        expose_headers=["ETag", "Location", "Retry-After", "X-Request-ID"],
    )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory app.main:app_factory``."""
    return create_app()
