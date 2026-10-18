"""Scan pipeline: extraction → validation → normalisation → scoring → persistence.

This is the worker side of guide §4.2. It is written as plain async functions over the
``Services`` container so the ARQ worker, the inline queue and the tests share one code path.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.db.models import NutritionFacts, Product, Scan, ScanStatus, ScorePenalty
from app.schemas.extraction import Extraction
from app.services.cache import BarcodeLock
from app.services.context import Services
from app.services.extraction.base import ExtractionError, SchemaError
from app.services.normalise.normaliser import normalise
from app.services.scoring import SCORING_VERSION, NutritionInput, ScoreResult, parse_ingredients
from app.services.scoring import score as run_engine

log = structlog.get_logger(__name__)

EXPECTED_ROLES = ["front", "nutrition", "ingredients"]

# NutritionInput field ↔ NutritionFacts column
NUTRITION_COLUMNS: dict[str, str] = {
    "energy_kcal": "energy_kcal",
    "sugars_g": "sugar_g",
    "added_sugars_g": "added_sugar_g",
    "carbs_g": "carbs_g",
    "fat_g": "fat_g",
    "sat_fat_g": "sat_fat_g",
    "trans_fat_g": "trans_fat_g",
    "salt_g": "salt_g",
    "fibre_g": "fibre_g",
    "protein_g": "protein_g",
}


def now() -> datetime:
    return datetime.now(UTC)


# --- nutrition rows ------------------------------------------------------------------


def nutrition_to_row(
    n: NutritionInput, scan_id: uuid.UUID, source: str, basis: str
) -> NutritionFacts:
    values = {col: getattr(n, field) for field, col in NUTRITION_COLUMNS.items()}
    return NutritionFacts(scan_id=scan_id, source=source, basis=basis, **values)


def row_to_nutrition(row: NutritionFacts) -> NutritionInput:
    return NutritionInput(**{field: getattr(row, col) for field, col in NUTRITION_COLUMNS.items()})


async def current_nutrition(session: AsyncSession, scan_id: uuid.UUID) -> NutritionFacts | None:
    """The user's corrected row wins over the LLM row."""
    rows = (
        await session.scalars(select(NutritionFacts).where(NutritionFacts.scan_id == scan_id))
    ).all()
    by_source = {r.source: r for r in rows}
    return by_source.get("user") or by_source.get("llm")


async def save_nutrition(
    session: AsyncSession, scan: Scan, n: NutritionInput, *, source: str, basis: str
) -> None:
    await session.execute(
        delete(NutritionFacts).where(
            NutritionFacts.scan_id == scan.id, NutritionFacts.source == source
        )
    )
    session.add(nutrition_to_row(n, scan.id, source, basis))


# --- scoring ---------------------------------------------------------------------------


async def apply_score(
    svc: Services, session: AsyncSession, scan: Scan, nutrition: NutritionInput | None
) -> ScoreResult:
    """Run the engine on the scan's current data and persist score, band and penalty rows."""
    extra_codes = (scan.extraction or {}).get("additive_codes", [])
    result = run_engine(
        nutrition,
        parse_ingredients(scan.ingredients or []),
        svc.additives,
        is_beverage=scan.is_beverage,
        extra_additive_codes=extra_codes,
    )
    if result.unrated_additives:
        log.info("unrated_additives", scan_id=str(scan.id), codes=result.unrated_additives)

    scan.score = result.score
    scan.band = result.band.value
    scan.is_partial = result.is_partial
    scan.result = result.model_dump(mode="json")
    scan.scoring_version = result.scoring_version
    scan.status = ScanStatus.DONE
    scan.completed_at = now()

    await session.execute(delete(ScorePenalty).where(ScorePenalty.scan_id == scan.id))
    for i, p in enumerate(result.penalties):
        session.add(
            ScorePenalty(
                scan_id=scan.id,
                position=i,
                kind="penalty",
                factor=p.factor,
                points_lost=p.points,
                reason=p.reason,
            )
        )
    for j, pos in enumerate(result.positives, start=len(result.penalties)):
        session.add(
            ScorePenalty(
                scan_id=scan.id,
                position=j,
                kind="positive",
                factor=pos.factor,
                points_lost=-pos.points,
                reason=pos.reason,
            )
        )
    return result


# --- products & cache ------------------------------------------------------------------


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def product_fingerprint(barcode: str | None, brand: str | None, name: str | None) -> str | None:
    if barcode:
        basis = f"barcode:{barcode}"
    elif _norm(name):
        basis = f"name:{_norm(brand)}|{_norm(name)}"
    else:
        return None
    return hashlib.sha256(basis.encode()).hexdigest()


async def upsert_product(session: AsyncSession, scan: Scan, ex: Extraction) -> Product | None:
    fingerprint = product_fingerprint(scan.barcode, ex.brand, ex.product_name)
    if fingerprint is None:
        return None
    product = await session.scalar(select(Product).where(Product.fingerprint == fingerprint))
    if product is None:
        product = Product(
            fingerprint=fingerprint,
            barcode=scan.barcode,
            name=ex.product_name,
            brand=ex.brand,
            category=ex.category_guess,
            is_beverage=scan.is_beverage,
        )
        session.add(product)
        await session.flush()
    else:
        product.name = product.name or ex.product_name
        product.brand = product.brand or ex.brand
    scan.product_id = product.id
    return product


def snapshot_for_cache(
    scan: Scan, nutrition: NutritionInput | None, product: Product | None
) -> dict[str, Any]:
    return {
        "scan_id": str(scan.id),
        "scored_at": (scan.completed_at or now()).isoformat(),
        "product": {
            "id": str(product.id) if product else None,
            "name": product.name if product else None,
            "brand": product.brand if product else None,
            "category": product.category if product else None,
        },
        "nutrition": nutrition.model_dump() if nutrition else None,
        "basis": "per_100ml" if scan.is_beverage else "per_100g",
        "ingredients": scan.ingredients,
        "additive_codes": (scan.extraction or {}).get("additive_codes", []),
        "is_beverage": scan.is_beverage,
        "confidence": scan.confidence,
        "prompt_version": scan.prompt_version,
        "scoring_version": scan.scoring_version,
        "result": scan.result,
    }


async def apply_snapshot(
    svc: Services, session: AsyncSession, scan: Scan, snap: dict[str, Any]
) -> None:
    """Fill a new scan from a cached product result (fast path, no LLM call)."""
    product_id = (snap.get("product") or {}).get("id")
    scan.product_id = uuid.UUID(product_id) if product_id else None
    scan.from_cache = True
    scan.is_beverage = bool(snap.get("is_beverage"))
    scan.ingredients = list(snap.get("ingredients") or [])
    scan.extraction = {
        "additive_codes": snap.get("additive_codes", []),
        "cached_from": snap.get("scan_id"),
    }
    scan.confidence = snap.get("confidence")
    scan.prompt_version = snap.get("prompt_version")
    nutrition = NutritionInput(**snap["nutrition"]) if snap.get("nutrition") else None
    if nutrition is not None:
        await save_nutrition(
            session, scan, nutrition, source="llm", basis=snap.get("basis", "per_100g")
        )
    # Always re-run the (cheap, deterministic) engine so a cached product is scored with the
    # current rules even if the scoring version changed since it was cached.
    await apply_score(svc, session, scan, nutrition)


# --- failure helpers -------------------------------------------------------------------


def problem(
    slug: str, title: str, detail: str, status: int = 422, retake: list[str] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"https://foodscore.app/errors/{slug}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if retake:
        body["retake"] = retake
    return body


# What the user sees for each failure kind (ExtractionError.kind): slug, title, detail, status.
PROVIDER_ERRORS: dict[str, tuple[str, str, str, int]] = {
    "unavailable": (
        "provider-unavailable",
        "Label reading is temporarily unavailable",
        "Our AI provider is not responding. Please try again in a few minutes.",
        503,
    ),
    "rate_limit": (
        "provider-busy",
        "Label reading is busy right now",
        "Too many scans are being read at once. Please wait a minute and try again.",
        503,
    ),
    "config": (
        "provider-misconfigured",
        "Label reading is not set up correctly",
        "The AI provider rejected the request. The site owner needs to check the API key "
        "and model settings.",
        502,
    ),
    "blocked": (
        "unreadable-label",
        "Couldn't read these photos",
        "The AI provider declined to process these photos. Please retake them showing only "
        "the packet.",
        422,
    ),
}


async def _fail(session: AsyncSession, scan: Scan, error: dict[str, Any]) -> None:
    scan.status = ScanStatus.FAILED
    scan.error = error
    scan.completed_at = now()
    metrics.SCANS.labels(status="FAILED").inc()


async def _delete_images(svc: Services, scan: Scan) -> None:
    if scan.image_keys:
        try:
            await svc.store.delete(list(scan.image_keys))
        except Exception:
            log.warning("image_delete_failed", scan_id=str(scan.id), exc_info=True)
        scan.image_keys = []


# --- the job ---------------------------------------------------------------------------


async def _wait_for_lock(lock: BarcodeLock, timeout_s: float = 60.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await lock.acquire():
            return True
        await asyncio.sleep(0.5)
    return False


async def process_scan(svc: Services, scan_id: uuid.UUID) -> None:
    structlog.contextvars.bind_contextvars(scan_id=str(scan_id))
    try:
        await _process(svc, scan_id)
    finally:
        structlog.contextvars.unbind_contextvars("scan_id")


async def _process(svc: Services, scan_id: uuid.UUID) -> None:
    async with svc.sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None or scan.status not in (ScanStatus.QUEUED, ScanStatus.PROCESSING):
            return  # deleted, or already handled (job retried after success)
        scan.status = ScanStatus.PROCESSING
        scan.started_at = now()
        await session.commit()

        lock: BarcodeLock | None = None
        try:
            if scan.barcode:
                lock = BarcodeLock(svc.redis, scan.barcode)
                await _wait_for_lock(lock)
                # Another worker may have scored this barcode while we waited (edge 41).
                snap = await svc.cache.get(scan.barcode)
                if snap:
                    metrics.CACHE_HITS.inc()
                    await apply_snapshot(svc, session, scan, snap)
                    await _delete_images(svc, scan)
                    await session.commit()
                    metrics.SCANS.labels(status="DONE").inc()
                    return
            await _extract_and_score(svc, session, scan)
            await session.commit()
        except Exception:
            await session.rollback()
            scan = await session.get(Scan, scan_id)
            if scan is not None and scan.status == ScanStatus.PROCESSING:
                await _fail(
                    session,
                    scan,
                    problem(
                        "internal", "Something went wrong", "Please try the scan again.", status=500
                    ),
                )
                await _delete_images(svc, scan)
                await session.commit()
            raise
        finally:
            if lock is not None:
                await lock.release()


async def _extract_and_score(svc: Services, session: AsyncSession, scan: Scan) -> None:
    settings = svc.settings
    images = [await svc.store.get(key) for key in scan.image_keys]
    provider = getattr(svc.extractor, "name", "unknown")
    try:
        res = await svc.extractor.extract(images, settings.prompt_version)
    except SchemaError as exc:
        metrics.LLM_FAILURES.labels(provider=exc.provider or provider, kind="schema").inc()
        await _fail(
            session,
            scan,
            problem(
                "unreadable-label",
                "Couldn't read the label",
                "Please retake the photos in good light.",
                retake=EXPECTED_ROLES,
            ),
        )
        await _delete_images(svc, scan)
        return
    except ExtractionError as exc:
        metrics.LLM_FAILURES.labels(provider=exc.provider or provider, kind=exc.kind).inc()
        # The full provider message is logged (never shown); users get a safe short code.
        log.error(
            "extraction_failed",
            error=str(exc),
            code=exc.code,
            kind=exc.kind,
            retryable=exc.retryable,
            cause=repr(exc.__cause__)[:300] if exc.__cause__ else None,
        )
        body = PROVIDER_ERRORS.get(exc.kind, PROVIDER_ERRORS["unavailable"])
        error = problem(*body)
        error["provider_error"] = exc.code
        await _fail(session, scan, error)
        await _delete_images(svc, scan)
        return

    ex = res.extraction
    scan.provider = res.provider
    scan.model = res.model
    scan.prompt_version = res.prompt_version
    scan.llm_latency_ms = res.latency_ms
    scan.llm_cost_usd = res.cost_usd
    scan.extraction = ex.model_dump(mode="json")
    metrics.LLM_LATENCY.labels(provider=res.provider).observe(res.latency_ms / 1000)
    metrics.LLM_COST.labels(provider=res.provider).inc(res.cost_usd)
    log.info(
        "extraction_done",
        provider=res.provider,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
        repaired=res.repaired,
    )

    # Images are no longer needed once extraction succeeded (privacy by design, ADR-5).
    await _delete_images(svc, scan)

    if not ex.is_food_label:
        await _fail(
            session,
            scan,
            problem(
                "not-food-label",
                "This doesn't look like a food label",
                "Please photograph the front, nutrition table and ingredients of a packaged food.",
                retake=EXPECTED_ROLES,
            ),
        )
        return

    outcome = normalise(ex, review_threshold=settings.review_confidence_threshold)
    if outcome.nutrition_unreadable:
        issue = next((i.issue for i in ex.legibility_issues if i.image == "nutrition"), "")
        await _fail(
            session,
            scan,
            problem(
                "unreadable-label",
                "Couldn't read the nutrition table",
                f"The nutrition photo is unreadable{': ' + issue if issue else ''}. Please retake it.",
                retake=["nutrition"],
            ),
        )
        return

    issues = [{"field": i.field, "code": i.code, "message": i.message} for i in outcome.issues]
    roles = list(ex.image_roles)
    if sorted(roles) != sorted(EXPECTED_ROLES):
        missing = [r for r in EXPECTED_ROLES if r not in roles]
        issues.append(
            {
                "field": "images",
                "code": "photo_role_mismatch",
                "message": f"Could not find a {', '.join(missing)} photo",
            }
        )
    elif roles != EXPECTED_ROLES:
        log.info("image_roles_reassigned", roles=roles)  # edge case 3: auto-reassigned
    if ex.multiple_products:
        issues.append(
            {
                "field": "images",
                "code": "multiple_products",
                "message": "Several products are visible; scored the dominant one",
            }
        )
    for li in ex.legibility_issues:
        issues.append({"field": li.image, "code": "legibility", "message": li.issue})

    scan.is_beverage = outcome.is_beverage
    scan.ingredients = list(ex.ingredients)
    scan.confidence = outcome.confidence
    scan.field_confidence = outcome.field_confidence
    scan.review_issues = issues

    if outcome.nutrition is not None:
        await save_nutrition(session, scan, outcome.nutrition, source="llm", basis=outcome.basis)
    product = await upsert_product(session, scan, ex)

    if outcome.needs_review:
        scan.status = ScanStatus.NEEDS_REVIEW
        metrics.SCANS.labels(status="NEEDS_REVIEW").inc()
        return

    await apply_score(svc, session, scan, outcome.nutrition)
    metrics.SCANS.labels(status="DONE").inc()
    if product is not None:
        product.latest_scan_id = scan.id  # newer scan = newer recipe version (edge 31)
    if scan.barcode:
        await svc.cache.set(scan.barcode, snapshot_for_cache(scan, outcome.nutrition, product))


__all__ = [
    "SCORING_VERSION",
    "apply_score",
    "apply_snapshot",
    "current_nutrition",
    "process_scan",
    "row_to_nutrition",
    "save_nutrition",
    "snapshot_for_cache",
]
