"""Scan endpoints (guide §8.2). Upload → 202 + poll, or 200 straight from the barcode cache."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, Header, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import (
    Owner,
    OwnerDep,
    ServicesDep,
    SessionDep,
    UserDep,
    enforce_rate_limit,
    get_owned_scan,
)
from app.core import metrics
from app.core.errors import AppError
from app.db.models import TERMINAL_STATUSES, Feedback, Product, Scan, ScanStatus
from app.schemas.api import (
    CapOut,
    FactorOut,
    FeedbackIn,
    FeedbackOut,
    NutritionOut,
    NutritionPatch,
    ProductOut,
    ReviewIssueOut,
    ScanOut,
    ScanPage,
    ScanSummaryOut,
)
from app.services import images as image_svc
from app.services.barcode import detect_barcode
from app.services.context import Services
from app.services.pipeline import (
    NUTRITION_COLUMNS,
    apply_score,
    apply_snapshot,
    current_nutrition,
    row_to_nutrition,
    save_nutrition,
)
from app.services.scoring import NutritionInput

router = APIRouter(prefix="/scans", tags=["scans"])
log = structlog.get_logger(__name__)

PAGE_SIZE = 20


# --- serialisation ---------------------------------------------------------------------


async def scan_out(session: SessionDep, scan: Scan) -> ScanOut:
    result: dict[str, Any] = scan.result or {}
    product = await session.get(Product, scan.product_id) if scan.product_id else None
    row = await current_nutrition(session, scan.id)
    nutrition = None
    if row is not None:
        nutrition = NutritionOut(
            basis=row.basis,
            source="user" if row.source == "user" else "llm",
            **{field: getattr(row, col) for field, col in NUTRITION_COLUMNS.items()},
        )

    def factors(key: str) -> list[FactorOut]:
        return [
            FactorOut(
                factor=f["factor"],
                label=f["label"],
                points=round(f["points"], 2),
                reason=f["reason"],
                code=f.get("code"),
            )
            for f in result.get(key, [])
        ]

    extraction = scan.extraction or {}
    return ScanOut(
        id=scan.id,
        status=scan.status.value,
        score=scan.score,
        band=scan.band,
        verdict=result.get("verdict"),
        confidence=scan.confidence,
        is_partial=scan.is_partial,
        is_beverage=scan.is_beverage,
        user_corrected=scan.user_corrected,
        from_cache=scan.from_cache,
        nova=result.get("nova"),
        product=ProductOut(
            name=product.name if product else extraction.get("product_name"),
            brand=product.brand if product else extraction.get("brand"),
            barcode=scan.barcode,
            category=product.category if product else extraction.get("category_guess"),
        ),
        penalties=factors("penalties"),
        positives=factors("positives"),
        caps_applied=[CapOut(**c) for c in result.get("caps_applied", [])],
        nutrition=nutrition,
        ingredients=list(scan.ingredients or []),
        flagged_ingredients=list(result.get("flagged_ingredients", [])),
        unrated_additives=list(result.get("unrated_additives", [])),
        review_issues=[ReviewIssueOut(**i) for i in scan.review_issues or []],
        field_confidence=dict(scan.field_confidence or {}),
        error=scan.error,
        prompt_version=scan.prompt_version,
        scoring_version=scan.scoring_version,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


def _etag(scan: Scan) -> str:
    return f'W/"{scan.id.hex[:12]}-{int(scan.updated_at.timestamp() * 1000)}-{scan.status.value}"'


# --- create ----------------------------------------------------------------------------


async def _check_quota(svc: Services, owner: Owner) -> list[str]:
    """Consume one new-scan quota unit for the owner (and IP for guests). Returns keys to refund."""
    s = svc.settings
    limits = [(owner.key, s.guest_daily_scan_quota if owner.is_guest else s.user_daily_scan_quota)]
    if owner.is_guest:
        limits.append((f"ip:{owner.ip_hash}", s.guest_daily_scan_quota * 3))
    consumed: list[str] = []
    for key, limit in limits:
        used = await svc.quotas.consume(key)
        consumed.append(key)
        if used > limit:
            for k in consumed:
                await svc.quotas.refund(k)
            detail = (
                f"Guests can scan {s.guest_daily_scan_quota} new products a day. Sign in for more."
                if owner.is_guest
                else f"You have used all {limit} new scans for today. Cached products are still free."
            )
            raise AppError(
                429,
                "quota-exceeded",
                "Daily scan limit reached",
                detail,
                headers={"Retry-After": "3600"},
            )

    used_global = await svc.quotas.consume_global()
    consumed.append("__global__")
    if used_global >= int(s.global_daily_scan_budget * 0.8):
        log.warning("llm_budget_alarm", used=used_global, budget=s.global_daily_scan_budget)
    if used_global > s.global_daily_scan_budget:
        for k in consumed:
            await svc.quotas.refund(k)
        raise AppError(
            503,
            "budget-exhausted",
            "New scans are paused for today",
            "We've reached today's AI budget. Previously scanned products still work.",
            headers={"Retry-After": "3600"},
        )
    return consumed


async def _find_idempotent(session: SessionDep, key: str | None) -> Scan | None:
    if not key:
        return None
    return await session.scalar(select(Scan).where(Scan.idempotency_key == key))


def _respond(response: Response, out: ScanOut, status_code: int) -> ScanOut:
    # Set status/headers on the injected response (not a new JSONResponse) so cookies set by
    # dependencies — e.g. the guest cookie — are kept.
    response.status_code = status_code
    response.headers["Location"] = f"/api/v1/scans/{out.id}"
    return out


@router.post(
    "",
    response_model=ScanOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": ScanOut, "description": "Served from the barcode cache"}},
)
async def create_scan(
    svc: ServicesDep,
    session: SessionDep,
    owner: OwnerDep,
    response: Response,
    front: Annotated[UploadFile, File(description="Front of the pack")],
    nutrition: Annotated[UploadFile, File(description="Nutrition facts table")],
    ingredients: Annotated[UploadFile, File(description="Ingredients list")],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
) -> ScanOut:
    s = svc.settings
    await enforce_rate_limit(svc, f"scan:{owner.key}", s.rate_limit_scan_per_min)
    await enforce_rate_limit(svc, f"scan-ip:{owner.ip_hash}", s.rate_limit_scan_per_min * 2)

    idem = f"{owner.key}:{idempotency_key}" if idempotency_key else None
    existing = await _find_idempotent(session, idem)
    if existing is not None:  # edge case 35: double submit returns the original scan
        out = await scan_out(session, existing)
        return _respond(response, out, 200 if existing.status in TERMINAL_STATUSES else 202)

    # Read with a hard cap so a huge upload cannot exhaust memory.
    raw: dict[str, bytes] = {}
    for role, upload in (("front", front), ("nutrition", nutrition), ("ingredients", ingredients)):
        data = await upload.read(s.max_image_bytes + 1)
        raw[role] = data
    prepared = [
        await asyncio.to_thread(
            image_svc.prepare, role, data, max_bytes=s.max_image_bytes, max_px=s.max_image_px
        )
        for role, data in raw.items()
    ]
    dupes = image_svc.find_duplicates(prepared)
    if dupes:
        missing = [r for r in image_svc.ROLES if r in dupes]
        raise AppError(
            422,
            "duplicate-image",
            "Two photos are the same",
            f"Please retake the {' and '.join(missing)} photo — it matches another photo.",
            retake=missing,
        )

    barcode = await asyncio.to_thread(detect_barcode, *(p.image for p in prepared))
    scan_id = uuid.uuid4()
    scan = Scan(
        id=scan_id,
        user_id=owner.user_id,
        guest_id=owner.guest_id,
        idempotency_key=idem,
        barcode=barcode,
        status=ScanStatus.QUEUED,
    )

    # Fast path: product already scored (edge cases / ADR-3). Does not count against quota.
    snapshot = await svc.cache.get(barcode) if barcode else None
    if snapshot:
        metrics.CACHE_HITS.inc()
        session.add(scan)
        await apply_snapshot(svc, session, scan, snapshot)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await _find_idempotent(session, idem)
            assert existing is not None
            return _respond(response, await scan_out(session, existing), 200)
        metrics.SCANS.labels(status="DONE").inc()
        return _respond(response, await scan_out(session, scan), 200)
    if barcode:
        metrics.CACHE_MISSES.inc()

    consumed = await _check_quota(svc, owner)
    keys = [f"scans/{scan_id}/{p.role}.jpg" for p in prepared]
    for key, p in zip(keys, prepared, strict=True):
        await svc.store.put(key, p.data)
    scan.image_keys = keys
    session.add(scan)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await svc.store.delete(keys)
        for k in consumed:
            await svc.quotas.refund(k)
        existing = await _find_idempotent(session, idem)
        if existing is None:
            raise
        return _respond(response, await scan_out(session, existing), 202)

    assert svc.queue is not None
    try:
        await svc.queue.enqueue_scan(scan_id)
    except Exception as exc:  # edge case 39: queue unavailable → 503 with Retry-After
        log.error("enqueue_failed", error=str(exc))
        scan.status = ScanStatus.FAILED
        scan.error = {
            "type": "https://foodscore.app/errors/queue-unavailable",
            "title": "Service busy",
            "status": 503,
        }
        scan.image_keys = []
        await session.commit()
        await svc.store.delete(keys)
        for k in consumed:
            await svc.quotas.refund(k)
        raise AppError(
            503,
            "queue-unavailable",
            "Service busy",
            "Please try again shortly.",
            headers={"Retry-After": "30"},
        ) from exc

    log.info("scan_queued", scan_id=str(scan_id), barcode=bool(barcode))
    return _respond(response, await scan_out(session, scan), 202)


# --- read ------------------------------------------------------------------------------


@router.get("/{scan_id}", response_model=ScanOut, responses={304: {"description": "Not modified"}})
async def get_scan(
    scan_id: uuid.UUID,
    session: SessionDep,
    owner: OwnerDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> ScanOut | Response:
    scan = await get_owned_scan(scan_id, owner, session)
    etag = _etag(scan)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    return await scan_out(session, scan)


@router.get("/{scan_id}/events")
async def scan_events(
    scan_id: uuid.UUID, request: Request, svc: ServicesDep, owner: OwnerDep
) -> StreamingResponse:
    """Server-Sent Events alternative to polling. Emits a ``status`` event on every change."""
    async with svc.sessionmaker() as session:
        await get_owned_scan(scan_id, owner, session)

    async def stream() -> AsyncIterator[str]:
        last: str | None = None
        for _ in range(180):  # ≈ 3 minutes max, then the client falls back to polling
            if await request.is_disconnected():
                return
            async with svc.sessionmaker() as session:
                scan = await session.get(Scan, scan_id)
                if scan is None:
                    return
                if scan.status.value != last:
                    last = scan.status.value
                    yield f"event: status\ndata: {json.dumps({'id': str(scan_id), 'status': last})}\n\n"
                if scan.status in TERMINAL_STATUSES or scan.status == ScanStatus.NEEDS_REVIEW:
                    return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


def _encode_cursor(scan: Scan) -> str:
    return base64.urlsafe_b64encode(f"{scan.created_at.isoformat()}|{scan.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, sid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        ts = datetime.fromisoformat(created)
        return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)), uuid.UUID(sid)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(400, "bad-cursor", "Invalid pagination cursor") from exc


@router.get("", response_model=ScanPage)
async def list_scans(
    session: SessionDep,
    owner: UserDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = PAGE_SIZE,
) -> ScanPage:
    stmt = owner.scope(select(Scan)).options(selectinload(Scan.product))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.join(Product, Scan.product_id == Product.id).where(
            or_(Product.name.ilike(like), Product.brand.ilike(like))
        )
    if cursor:
        ts, sid = _decode_cursor(cursor)
        stmt = stmt.where(or_(Scan.created_at < ts, (Scan.created_at == ts) & (Scan.id < sid)))
    rows = (
        await session.scalars(
            stmt.order_by(Scan.created_at.desc(), Scan.id.desc()).limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    items = [
        ScanSummaryOut(
            id=s.id,
            status=s.status.value,
            score=s.score,
            band=s.band,
            product=ProductOut(
                name=s.product.name if s.product else (s.extraction or {}).get("product_name"),
                brand=s.product.brand if s.product else (s.extraction or {}).get("brand"),
                barcode=s.barcode,
                category=s.product.category if s.product else None,
            ),
            is_partial=s.is_partial,
            user_corrected=s.user_corrected,
            created_at=s.created_at,
        )
        for s in page
    ]
    return ScanPage(
        items=items, next_cursor=_encode_cursor(page[-1]) if len(rows) > limit else None
    )


# --- corrections -----------------------------------------------------------------------


@router.patch("/{scan_id}/nutrition", response_model=ScanOut)
async def correct_nutrition(
    scan_id: uuid.UUID, body: NutritionPatch, svc: ServicesDep, session: SessionDep, owner: OwnerDep
) -> ScanOut:
    """Edit extracted values and re-score. Only this scan changes; the shared cache does not."""
    scan = await get_owned_scan(scan_id, owner, session)
    if scan.status not in (ScanStatus.DONE, ScanStatus.NEEDS_REVIEW):
        raise AppError(409, "not-editable", f"A {scan.status.value} scan cannot be edited")
    row = await current_nutrition(session, scan.id)
    current = row_to_nutrition(row) if row else NutritionInput()
    changes = body.model_dump(exclude_unset=True)
    if "ingredients" in changes:
        scan.ingredients = [i for i in (changes.pop("ingredients") or []) if i.strip()]
    if "is_beverage" in changes:
        scan.is_beverage = bool(changes.pop("is_beverage"))
    for field, value in changes.items():
        if getattr(current, field) != value:
            metrics.USER_CORRECTIONS.labels(field=field).inc()
    merged = current.model_copy(update=changes)
    basis = "per_100ml" if scan.is_beverage else "per_100g"
    await save_nutrition(session, scan, merged, source="user", basis=basis)
    scan.user_corrected = True
    scan.review_issues = []
    has_values = merged.core_present() > 0
    await apply_score(svc, session, scan, merged if has_values else None)
    await session.commit()
    return await scan_out(session, scan)


@router.post("/{scan_id}/confirm", response_model=ScanOut)
async def confirm_scan(
    scan_id: uuid.UUID, svc: ServicesDep, session: SessionDep, owner: OwnerDep
) -> ScanOut:
    """Accept low-confidence values as they are and score them (NEEDS_REVIEW → DONE)."""
    scan = await get_owned_scan(scan_id, owner, session)
    if scan.status != ScanStatus.NEEDS_REVIEW:
        raise AppError(409, "not-in-review", "Only scans waiting for review can be confirmed")
    if any(i.get("code") == "serving_size_missing" for i in scan.review_issues or []):
        raise AppError(
            422,
            "needs-edits",
            "Values need editing first",
            "Only per-serving values were found. Enter per-100 g values or the serving size.",
        )
    row = await current_nutrition(session, scan.id)
    await apply_score(svc, session, scan, row_to_nutrition(row) if row else None)
    await session.commit()
    return await scan_out(session, scan)


# --- delete & feedback -----------------------------------------------------------------


@router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan(
    scan_id: uuid.UUID, svc: ServicesDep, session: SessionDep, owner: OwnerDep
) -> Response:
    scan = await get_owned_scan(scan_id, owner, session)
    if scan.image_keys:
        await svc.store.delete(list(scan.image_keys))
    await session.delete(scan)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{scan_id}/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def report_problem(
    scan_id: uuid.UUID, body: FeedbackIn, svc: ServicesDep, session: SessionDep, owner: OwnerDep
) -> FeedbackOut:
    await enforce_rate_limit(svc, f"feedback:{owner.key}", 10)
    await get_owned_scan(scan_id, owner, session)
    fb = Feedback(
        scan_id=scan_id,
        user_id=owner.user_id,
        type=body.type,
        field=body.field,
        comment=body.comment,
    )
    session.add(fb)
    await session.commit()
    log.info("feedback_received", type=body.type, field=body.field)
    return FeedbackOut(id=fb.id)
