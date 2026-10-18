"""End-to-end scan flow through the HTTP API (guide §4.2, §8.2, edge cases)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.db.models import Scan, ScanStatus
from app.services.extraction.base import ExtractionError
from tests.api.conftest import drain, register
from tests.images import photo, photo_set

BARCODE = "890123456789"  # → EAN-13 8901234567890


async def post_scan(client, headers=None, *, seed=1, barcode=None, key=None, files=None):
    h = dict(headers or {})
    if key:
        h["Idempotency-Key"] = key
    return await client.post("/api/v1/scans", files=files or photo_set(seed, barcode), headers=h)


async def test_happy_path_new_scan(client, services):
    headers = await register(client)
    r = await post_scan(client, headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] in ("QUEUED", "PROCESSING")
    assert r.headers["location"] == f"/api/v1/scans/{body['id']}"

    await drain(services)
    r = await client.get(f"/api/v1/scans/{body['id']}", headers=headers)
    assert r.status_code == 200
    scan = r.json()
    assert scan["status"] == "DONE"
    assert scan["score"] == 39
    assert scan["band"] == "BAD"
    assert scan["product"]["name"] == "Choco Cream Biscuit"
    assert scan["penalties"][0]["factor"] == "sugar"
    assert scan["penalties"][0]["reason"] == "Sugar 30 g/100 g is high (> 22.5 g)"
    assert scan["positives"][0]["factor"] == "protein"
    assert scan["nutrition"]["basis"] == "per_100g"
    assert scan["nutrition"]["source"] == "llm"
    assert scan["disclaimer"].startswith("For general information only")
    assert "Artificial flavour (chocolate)" in scan["flagged_ingredients"]


async def test_images_are_deleted_after_processing(client, services, settings):
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    async with services.sessionmaker() as s:
        scan = await s.get(Scan, __import__("uuid").UUID(r.json()["id"]))
        assert scan.image_keys == []
    from pathlib import Path

    assert not list(Path(settings.storage_local_dir).rglob("*.jpg"))


async def test_etag_returns_304_when_unchanged(client, services):
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    url = f"/api/v1/scans/{r.json()['id']}"
    first = await client.get(url, headers=headers)
    etag = first.headers["etag"]
    second = await client.get(url, headers={**headers, "If-None-Match": etag})
    assert second.status_code == 304


async def test_barcode_cache_fast_path(client, services, extractor):
    headers = await register(client)
    r = await post_scan(client, headers, seed=1, barcode=BARCODE)
    assert r.status_code == 202
    await drain(services)
    assert extractor.calls == 1

    # Same product, different photos → served from cache, no LLM call.
    r2 = await post_scan(client, headers, seed=7, barcode=BARCODE)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "DONE"
    assert r2.json()["from_cache"] is True
    assert r2.json()["score"] == 39
    assert r2.json()["product"]["barcode"] == "8901234567890"
    assert extractor.calls == 1

    # Public product endpoint
    p = await client.get("/api/v1/products/8901234567890")
    assert p.status_code == 200
    assert p.json()["score"] == 39
    assert p.headers["cache-control"] == "public, max-age=300"


async def test_cached_scans_do_not_count_against_quota(client, services, settings):
    settings.guest_daily_scan_quota = 1
    r = await post_scan(client, seed=1, barcode=BARCODE)  # guest, uses the 1 quota
    assert r.status_code == 202
    await drain(services)
    for seed in (11, 12, 13):
        r = await post_scan(client, seed=seed, barcode=BARCODE)
        assert r.status_code == 200, r.text
    r = await post_scan(client, seed=99)  # a new product → over quota
    assert r.status_code == 429
    assert r.json()["type"].endswith("/quota-exceeded")


async def test_idempotency_key_returns_same_scan(client, services, extractor):
    headers = await register(client)
    a = await post_scan(client, headers, key="abc-123")
    b = await post_scan(client, headers, seed=5, key="abc-123")
    assert a.json()["id"] == b.json()["id"]
    await drain(services)
    assert extractor.calls == 1


async def test_idempotency_keys_are_scoped_per_owner(client, services):
    h1 = await register(client, "one@example.com")
    h2 = await register(client, "two@example.com")
    a = await post_scan(client, h1, key="same")
    b = await post_scan(client, h2, key="same")
    assert a.json()["id"] != b.json()["id"]


async def test_other_users_cannot_read_scan(client, services):
    # IDOR: same 404 for "missing" and "not yours"
    h1 = await register(client, "one@example.com")
    h2 = await register(client, "two@example.com")
    r = await post_scan(client, h1)
    await drain(services)
    other = await client.get(f"/api/v1/scans/{r.json()['id']}", headers=h2)
    assert other.status_code == 404
    assert other.headers["content-type"].startswith("application/problem+json")


async def test_guest_can_poll_own_scan_but_has_no_history(client, services):
    r = await post_scan(client)
    assert r.status_code == 202
    assert "fs_guest" in r.cookies or client.cookies.get("fs_guest")
    await drain(services)
    own = await client.get(f"/api/v1/scans/{r.json()['id']}")
    assert own.json()["status"] == "DONE"
    history = await client.get("/api/v1/scans")
    assert history.status_code == 401


async def test_guest_quota(client, services, settings):
    for seed in range(settings.guest_daily_scan_quota):
        assert (await post_scan(client, seed=seed * 10)).status_code == 202
    r = await post_scan(client, seed=999)
    assert r.status_code == 429
    assert "Sign in" in r.json()["detail"]


async def test_rejects_non_image_file(client):
    files = photo_set()
    files["nutrition"] = ("nutrition.jpg", b"%PDF-1.4 not really an image", "image/jpeg")
    r = await post_scan(client, files=files)
    assert r.status_code == 415
    assert r.json()["retake"] == ["nutrition"]


async def test_rejects_heic_with_helpful_message(client):
    files = photo_set()
    files["front"] = ("front.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100, "image/heic")
    r = await post_scan(client, files=files)
    assert r.status_code == 415
    assert "HEIC" in r.json()["title"]


async def test_rejects_oversized_image(client, settings):
    settings.max_image_bytes = 1000
    r = await post_scan(client)
    assert r.status_code == 413


async def test_rejects_duplicate_photos(client):
    same = photo(42)
    files = {
        "front": ("a.jpg", same, "image/jpeg"),
        "nutrition": ("b.jpg", same, "image/jpeg"),
        "ingredients": ("c.jpg", photo(43), "image/jpeg"),
    }
    r = await post_scan(client, files=files)
    assert r.status_code == 422
    assert r.json()["retake"] == ["nutrition"]


async def test_missing_photo_is_validation_error(client):
    files = photo_set()
    del files["ingredients"]
    r = await post_scan(client, files=files)
    assert r.status_code == 422
    assert r.json()["type"].endswith("/validation-error")


async def test_exif_is_stripped_from_stored_images(services):
    from app.services.images import prepare

    img = Image.new("RGB", (100, 80), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90
    exif[0x8825] = {2: (1, 2, 3)}  # GPS
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    prepared = prepare("front", buf.getvalue(), max_bytes=5_000_000, max_px=1600)
    out = Image.open(io.BytesIO(prepared.data))
    assert not out.getexif()
    assert out.size == (80, 100)  # rotation applied before stripping


@pytest.mark.parametrize("fixture", ["not_food"])
async def test_not_a_food_label_fails_with_friendly_error(client, services, extractor, fixture):
    extractor.fixture = fixture
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["status"] == "FAILED"
    assert scan["error"]["type"].endswith("/not-food-label")
    assert scan["score"] is None


async def test_unreadable_nutrition_asks_for_that_photo(client, services, extractor):
    extractor.fixture = "unreadable_nutrition"
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["status"] == "FAILED"
    assert scan["error"]["retake"] == ["nutrition"]
    assert "blurry" in scan["error"]["detail"]
    assert scan["score"] is None


async def test_low_confidence_goes_to_review_then_confirm(client, services, extractor):
    extractor.fixture = "low_confidence_glare"
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    url = f"/api/v1/scans/{r.json()['id']}"
    scan = (await client.get(url, headers=headers)).json()
    assert scan["status"] == "NEEDS_REVIEW"
    assert scan["score"] is None
    assert any(i["code"] == "low_confidence" for i in scan["review_issues"])
    assert scan["field_confidence"]["salt_g"] == 0.45

    confirmed = await client.post(f"{url}/confirm", headers=headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "DONE"
    assert confirmed.json()["score"] is not None


async def test_low_confidence_results_are_not_cached(client, services, extractor):
    extractor.fixture = "low_confidence_glare"
    headers = await register(client)
    r = await post_scan(client, headers, barcode=BARCODE)
    await drain(services)
    await client.post(f"/api/v1/scans/{r.json()['id']}/confirm", headers=headers)
    assert await services.cache.get("8901234567890") is None


async def test_per_serving_label_is_normalised(client, services, extractor):
    extractor.fixture = "masala_noodles"
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["status"] == "DONE", scan["review_issues"]
    # 860 mg sodium per 70 g serving → 3.07 g salt per 100 g
    assert scan["nutrition"]["salt_g"] == pytest.approx(3.071, abs=0.01)
    assert scan["nova"] == 4


async def test_beverage_uses_drink_thresholds(client, services, extractor):
    extractor.fixture = "cola_drink"
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["is_beverage"] is True
    assert scan["nutrition"]["basis"] == "per_100ml"
    sugar = next(p for p in scan["penalties"] if p["factor"] == "sugar")
    assert "100 ml" in sugar["reason"]
    assert "INS 338" in scan["unrated_additives"]


async def test_user_correction_rescores_without_touching_cache(client, services):
    headers = await register(client)
    r = await post_scan(client, headers, barcode=BARCODE)
    await drain(services)
    url = f"/api/v1/scans/{r.json()['id']}"
    before = await services.cache.get("8901234567890")

    patched = await client.patch(
        f"{url}/nutrition", json={"sugars_g": 3, "sat_fat_g": 1}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["user_corrected"] is True
    assert body["nutrition"]["source"] == "user"
    assert body["nutrition"]["sugars_g"] == 3
    assert body["nutrition"]["energy_kcal"] == 480  # untouched fields kept
    assert body["score"] > 39
    assert await services.cache.get("8901234567890") == before  # edge case 34


async def test_correction_validation(client, services):
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    bad = await client.patch(
        f"/api/v1/scans/{r.json()['id']}/nutrition", json={"sugars_g": -1}, headers=headers
    )
    assert bad.status_code == 422


async def test_history_pagination_and_search(client, services, extractor):
    headers = await register(client)
    for i, fixture in enumerate(["chocolate_biscuit", "rolled_oats", "cola_drink"]):
        extractor.fixture = fixture
        await post_scan(client, headers, seed=i * 10)
        await drain(services)

    page = (await client.get("/api/v1/scans?limit=2", headers=headers)).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    assert page["items"][0]["product"]["name"] == "Cola Classic"  # newest first
    rest = (
        await client.get(f"/api/v1/scans?limit=2&cursor={page['next_cursor']}", headers=headers)
    ).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None

    found = (await client.get("/api/v1/scans?q=oats", headers=headers)).json()
    assert [i["product"]["name"] for i in found["items"]] == ["Rolled Oats"]


async def test_delete_scan(client, services):
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    url = f"/api/v1/scans/{r.json()['id']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404


async def test_feedback(client, services):
    headers = await register(client)
    r = await post_scan(client, headers)
    await drain(services)
    fb = await client.post(
        f"/api/v1/scans/{r.json()['id']}/feedback",
        json={"type": "wrong_value", "field": "sugars_g", "comment": "Label says 3 g"},
        headers=headers,
    )
    assert fb.status_code == 201


async def test_provider_outage_fails_cleanly(client, services, extractor, monkeypatch):
    async def boom(images, prompt_version):
        raise ExtractionError("down", retryable=True, provider="fake")

    monkeypatch.setattr(extractor, "extract", boom)
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["status"] == "FAILED"
    assert scan["error"]["status"] == 503


async def test_queue_unavailable_returns_503(client, services, monkeypatch):
    async def broken(scan_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(services.queue, "enqueue_scan", broken)
    r = await post_scan(client)
    assert r.status_code == 503
    assert r.headers["retry-after"] == "30"


async def test_reaper_fails_stuck_and_expires_stale(services):
    from datetime import UTC, datetime, timedelta

    from app.workers.reaper import reap_once

    old = datetime.now(UTC) - timedelta(hours=25)
    async with services.sessionmaker() as s:
        stuck = Scan(status=ScanStatus.PROCESSING, started_at=old)
        stale = Scan(status=ScanStatus.NEEDS_REVIEW)
        s.add_all([stuck, stale])
        await s.commit()
        stale.updated_at = old
        await s.commit()
    counts = await reap_once(services)
    assert counts == {"failed": 1, "expired": 1}
    async with services.sessionmaker() as s:
        assert (await s.get(Scan, stuck.id)).status == ScanStatus.FAILED
        assert (await s.get(Scan, stale.id)).status == ScanStatus.EXPIRED


async def test_concurrent_first_scans_of_same_barcode_make_one_llm_call(
    client, services, extractor, monkeypatch
):
    # edge case 41: Redis SET NX lock + re-check of the cache inside the worker.
    # Hold the first extraction open until both scans are queued; otherwise a fast machine can
    # finish job A before request B arrives, and B (correctly) becomes a cache hit.
    import asyncio

    gate = asyncio.Event()
    real_extract = extractor.extract

    async def held_extract(images, prompt_version):
        await gate.wait()
        return await real_extract(images, prompt_version)

    monkeypatch.setattr(extractor, "extract", held_extract)
    headers = await register(client)
    a = await post_scan(client, headers, seed=1, barcode=BARCODE)
    b = await post_scan(client, headers, seed=2, barcode=BARCODE)
    assert a.status_code == b.status_code == 202
    gate.set()
    await drain(services)
    assert extractor.calls == 1
    for r in (a, b):
        scan = (await client.get(f"/api/v1/scans/{r.json()['id']}", headers=headers)).json()
        assert scan["status"] == "DONE"
        assert scan["score"] == 39


async def test_reaper_fails_lost_queued_scans(services):
    from datetime import UTC, datetime, timedelta

    from app.workers.reaper import reap_once

    async with services.sessionmaker() as s:
        lost = Scan(status=ScanStatus.QUEUED, created_at=datetime.now(UTC) - timedelta(minutes=11))
        fresh = Scan(status=ScanStatus.QUEUED)
        s.add_all([lost, fresh])
        await s.commit()
    assert (await reap_once(services))["failed"] == 1
    async with services.sessionmaker() as s:
        assert (await s.get(Scan, lost.id)).status == ScanStatus.FAILED
        assert (await s.get(Scan, fresh.id)).status == ScanStatus.QUEUED


async def test_inline_reaper_loop_survives_errors(services, monkeypatch):
    import asyncio

    from app.workers import reaper

    calls = []

    async def flaky(svc):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db blip")
        return {"failed": 0, "expired": 0}

    monkeypatch.setattr(reaper, "reap_once", flaky)
    task = asyncio.create_task(reaper.run_forever(services, interval_s=0.01))
    await asyncio.sleep(0.1)
    task.cancel()
    assert len(calls) >= 2


@pytest.mark.parametrize(
    ("kind", "code", "slug", "status"),
    [
        ("unavailable", "gemini:UNAVAILABLE", "provider-unavailable", 503),
        ("rate_limit", "gemini:RESOURCE_EXHAUSTED", "provider-busy", 503),
        ("config", "gemini:NOT_FOUND", "provider-misconfigured", 502),
        ("blocked", "gemini:SAFETY", "unreadable-label", 422),
    ],
)
async def test_provider_failures_show_a_specific_message_and_code(
    client, services, extractor, monkeypatch, kind, code, slug, status
):
    async def failing(images, prompt_version):
        raise ExtractionError(
            "details for the log only", retryable=False, provider="gemini", kind=kind, code=code
        )

    monkeypatch.setattr(extractor, "extract", failing)
    r = await post_scan(client)
    await drain(services)
    scan = (await client.get(f"/api/v1/scans/{r.json()['id']}")).json()
    assert scan["status"] == "FAILED"
    assert scan["error"]["type"].endswith(f"/{slug}")
    assert scan["error"]["status"] == status
    assert scan["error"]["provider_error"] == code
    assert "details for the log only" not in str(scan["error"])  # provider text never shown
