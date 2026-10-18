"""In-process API harness: SQLite + fakeredis + replayed LLM fixtures + inline job queue.

Fast enough to run on every commit. The same tests run against real Postgres + Redis in
``tests/integration`` (Testcontainers) in CI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import fakeredis
import httpx
import pytest
from sqlalchemy import event

from app.core.config import Settings
from app.db.base import Base
from app.db.session import make_engine, make_sessionmaker
from app.main import create_app
from app.services.context import InlineQueue, Services
from app.services.extraction.fake import FakeExtractor
from app.services.pipeline import process_scan
from app.services.scoring import DEFAULT_ADDITIVES_PATH, load_additive_table
from app.services.storage import LocalImageStore

TEST_SECRET = "test-secret-that-is-at-least-32-characters-long"  # gitleaks:allow (dummy, test-only)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "redis_url": "redis://localhost:6379/0",
        "jwt_secret": TEST_SECRET,
        "cookie_secure": False,
        "job_mode": "inline",
        "llm_provider": "fake",
        "storage_backend": "local",
        "storage_local_dir": str(tmp_path / "images"),
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


async def build_test_services(settings: Settings, extractor: FakeExtractor) -> Services:
    engine = make_engine(settings.database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    svc = Services(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        redis=fakeredis.FakeAsyncRedis(),
        store=LocalImageStore(settings.storage_local_dir),
        extractor=extractor,
        additives=load_additive_table(DEFAULT_ADDITIVES_PATH),
    )
    svc.queue = InlineQueue(lambda scan_id: process_scan(svc, scan_id))
    return svc


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor("chocolate_biscuit")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
async def services(settings: Settings, extractor: FakeExtractor) -> AsyncIterator[Services]:
    svc = await build_test_services(settings, extractor)
    yield svc
    await svc.engine.dispose()


@pytest.fixture
async def client(settings: Settings, services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def drain(services: Services) -> None:
    assert isinstance(services.queue, InlineQueue)
    await services.queue.drain()


async def register(client: httpx.AsyncClient, email: str = "a@example.com") -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-42"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
