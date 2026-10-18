from __future__ import annotations

import pytest

from app.core.config import Settings
from tests.api.conftest import TEST_SECRET


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_ready_checks_db_and_redis(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_security_headers_and_request_id(client):
    r = await client.get("/health", headers={"X-Request-ID": "req_from_client"})
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-request-id"] == "req_from_client"


async def test_errors_are_problem_details(client):
    r = await client.get("/api/v1/scans/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    body = r.json()
    assert r.headers["content-type"].startswith("application/problem+json")
    assert set(body) >= {"type", "title", "status", "request_id"}


async def test_methodology_is_public_and_matches_engine(client):
    r = await client.get("/api/v1/methodology")
    assert r.status_code == 200
    body = r.json()
    assert body["weights"] == {"nutrient": 0.6, "ingredient": 0.3, "processing": 0.1}
    assert body["bands"][1] == {"max": 40, "band": "BAD", "label": "Bad"}
    assert all(a["source_url"].startswith("https://") for a in body["additives"])


async def test_unknown_product_404(client):
    assert (await client.get("/api/v1/products/8901234567890")).status_code == 404
    assert (await client.get("/api/v1/products/123")).status_code == 400


async def test_metrics_endpoint(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "foodscore_scans_total" in r.text


def test_settings_refuse_to_start_without_required_values():
    with pytest.raises(ValueError):
        Settings(_env_file=None, redis_url="redis://x", jwt_secret=TEST_SECRET)  # no DATABASE_URL
    with pytest.raises(ValueError, match="32 characters"):
        Settings(
            _env_file=None, database_url="sqlite://", redis_url="redis://x", jwt_secret="short"
        )
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(
            _env_file=None,
            database_url="sqlite://",
            redis_url="redis://x",
            jwt_secret=TEST_SECRET,
            llm_provider="claude",
        )
    with pytest.raises(ValueError, match="not allowed in production"):
        Settings(
            _env_file=None,
            database_url="sqlite://",
            redis_url="redis://x",
            jwt_secret=TEST_SECRET,
            environment="production",
        )


def test_env_example_is_a_valid_configuration():
    """The documented quick start (cp .env.example .env) must produce a bootable config."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[3] / ".env.example"
    settings = Settings(_env_file=example)
    assert settings.llm_provider == "fake"
    assert settings.llm_fallback_provider is None
    assert settings.cors_origins == ["http://localhost:3000"]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgres://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.neon.tech/db?ssl=require",
        ),
        ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db"),
    ],
)
def test_managed_postgres_urls_are_normalised(given, expected):
    from app.core.config import normalise_database_url

    assert normalise_database_url(given) == expected
