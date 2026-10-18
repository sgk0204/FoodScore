"""Integration tests against real Postgres 16 + Redis 7 (Testcontainers, needs Docker).

Run with:  pytest -m integration
CI runs these on every PR (guide §12: "API endpoints with real Postgres and Redis").
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis

from app.db.session import make_engine, make_sessionmaker
from app.main import create_app
from app.services.context import InlineQueue, Services
from app.services.extraction.fake import FakeExtractor
from app.services.pipeline import process_scan
from app.services.scoring import DEFAULT_ADDITIVES_PATH, load_additive_table
from app.services.storage import LocalImageStore
from tests.api.conftest import make_settings
from tests.images import photo_set

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def containers() -> Iterator[tuple[str, str]]:
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    with (
        PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg,
        RedisContainer("redis:7-alpine") as rd,
    ):
        db_url = pg.get_connection_url()
        redis_url = f"redis://{rd.get_container_host_ip()}:{rd.get_exposed_port(6379)}/0"
        # Migrations are part of what we test (edge case 42): run the real Alembic chain.
        env = {**os.environ, "DATABASE_URL": db_url}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True
        )
        check = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND, env=env)
        assert check.returncode == 0, "models and migrations have drifted"
        yield db_url, redis_url


@pytest.fixture
async def services(tmp_path: Path, containers: tuple[str, str]) -> AsyncIterator[Services]:
    db_url, redis_url = containers
    settings = make_settings(tmp_path, database_url=db_url, redis_url=redis_url)
    engine = make_engine(db_url)
    redis = Redis.from_url(redis_url)
    await redis.flushdb()
    svc = Services(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        redis=redis,
        store=LocalImageStore(settings.storage_local_dir),
        extractor=FakeExtractor(),
        additives=load_additive_table(DEFAULT_ADDITIVES_PATH),
    )
    svc.queue = InlineQueue(lambda sid: process_scan(svc, sid))
    yield svc
    await redis.aclose()
    await engine.dispose()


@pytest.fixture
async def client(services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(services.settings, services)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def test_full_flow_on_postgres(client: httpx.AsyncClient, services: Services) -> None:
    r = await client.post(
        "/api/v1/auth/register", json={"email": "pg@example.com", "password": "correct-horse-42"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    created = await client.post("/api/v1/scans", files=photo_set(3), headers=headers)
    assert created.status_code == 202
    assert isinstance(services.queue, InlineQueue)
    await services.queue.drain()
    scan = (await client.get(f"/api/v1/scans/{created.json()['id']}", headers=headers)).json()
    assert scan["status"] == "DONE" and scan["score"] == 39

    found = await client.get("/api/v1/scans?q=choco", headers=headers)  # ILIKE on Postgres
    assert len(found.json()["items"]) == 1
    assert (await client.get("/ready")).json()["checks"] == {"database": "ok", "redis": "ok"}
