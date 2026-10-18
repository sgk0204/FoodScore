from __future__ import annotations

from tests.api.conftest import drain, register
from tests.images import photo_set

PASSWORD = "correct-horse-42"


async def test_register_login_me(client):
    r = await client.post(
        "/api/v1/auth/register", json={"email": "Me@Example.com", "password": PASSWORD}
    )
    assert r.status_code == 201
    assert r.json()["token_type"] == "bearer"
    assert "fs_refresh" in r.cookies
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/auth" in cookie

    r = await client.post(
        "/api/v1/auth/login", json={"email": "me@example.com", "password": PASSWORD}
    )
    assert r.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["email"] == "me@example.com"


async def test_weak_password_rejected(client):
    r = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert r.status_code == 422
    assert r.json()["type"].endswith("/weak-password")


async def test_duplicate_email(client):
    await register(client, "dup@example.com")
    r = await client.post(
        "/api/v1/auth/register", json={"email": "dup@example.com", "password": PASSWORD}
    )
    assert r.status_code == 409


async def test_wrong_password_and_lockout(client, settings):
    await register(client, "lock@example.com")
    for _ in range(settings.login_max_failures):
        r = await client.post(
            "/api/v1/auth/login", json={"email": "lock@example.com", "password": "wrong-pass-99"}
        )
        assert r.status_code in (401, 429)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "lock@example.com", "password": PASSWORD}
    )
    assert r.status_code == 429
    assert r.json()["type"].endswith("/account-locked")


async def test_unknown_email_same_error_as_wrong_password(client):
    r = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401
    assert r.json()["type"].endswith("/invalid-credentials")


async def test_refresh_rotates_and_detects_reuse(client):
    r = await client.post(
        "/api/v1/auth/register", json={"email": "rot@example.com", "password": PASSWORD}
    )
    old_refresh = r.cookies["fs_refresh"]

    r1 = await client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    new_refresh = r1.cookies["fs_refresh"]
    assert new_refresh != old_refresh

    # Replaying the old (rotated) token revokes the whole family — including the new one.
    client.cookies.set("fs_refresh", old_refresh, path="/api/v1/auth")
    reuse = await client.post("/api/v1/auth/refresh")
    assert reuse.status_code == 401
    client.cookies.set("fs_refresh", new_refresh, path="/api/v1/auth")
    after = await client.post("/api/v1/auth/refresh")
    assert after.status_code == 401


async def test_logout_revokes_refresh(client):
    await client.post(
        "/api/v1/auth/register", json={"email": "out@example.com", "password": PASSWORD}
    )
    saved = client.cookies.get("fs_refresh")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set("fs_refresh", saved, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_invalid_access_token(client):
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_auth_rate_limit(client, settings):
    settings.rate_limit_auth_per_min = 3
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": f"r{i}@example.com", "password": PASSWORD}
            )
        ).status_code
        for i in range(5)
    ]
    assert codes[-1] == 429


async def test_delete_account_removes_all_data(client, services):
    headers = await register(client, "gone@example.com")
    r = await client.post("/api/v1/scans", files=photo_set(), headers=headers)
    await drain(services)
    scan_url = f"/api/v1/scans/{r.json()['id']}"
    assert (await client.delete("/api/v1/me", headers=headers)).status_code == 204

    from sqlalchemy import func, select

    from app.db.models import NutritionFacts, Scan, ScorePenalty

    async with services.sessionmaker() as s:
        for model in (Scan, NutritionFacts, ScorePenalty):
            assert await s.scalar(select(func.count()).select_from(model)) == 0
    # Token is still cryptographically valid but the account is gone
    assert (await client.get(scan_url, headers=headers)).status_code == 404
