from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import ServicesDep, SessionDep
from app.core.errors import AppError, not_found
from app.db.models import Product, Scan, ScanStatus
from app.schemas.api import FactorOut, ProductOut, PublicProductOut
from app.services.barcode import normalise_barcode

router = APIRouter(prefix="/products", tags=["products"])


def _factors(result: dict[str, Any], key: str) -> list[FactorOut]:
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


@router.get("/{barcode}", response_model=PublicProductOut)
async def get_product(
    barcode: str, response: Response, svc: ServicesDep, session: SessionDep
) -> PublicProductOut:
    """Public, cacheable product result. Never exposes who scanned it."""
    code = normalise_barcode(barcode)
    if code is None:
        raise AppError(
            400, "bad-barcode", "Invalid barcode", "Expected a valid EAN-8/EAN-13/UPC-A code."
        )

    product = await session.scalar(select(Product).where(Product.barcode == code))
    snap = await svc.cache.get(code)
    result: dict[str, Any] | None = snap.get("result") if snap else None
    scored_at = snap.get("scored_at") if snap else None
    if result is None and product is not None and product.latest_scan_id:
        scan = await session.get(Scan, product.latest_scan_id)
        if scan is not None and scan.status == ScanStatus.DONE and not scan.user_corrected:
            result = scan.result
            scored_at = scan.completed_at.isoformat() if scan.completed_at else None
    if result is None:
        raise not_found("Product")

    response.headers["Cache-Control"] = "public, max-age=300"
    snap_product = (snap or {}).get("product") or {}
    return PublicProductOut(
        barcode=code,
        product=ProductOut(
            name=product.name if product else snap_product.get("name"),
            brand=product.brand if product else snap_product.get("brand"),
            barcode=code,
            category=product.category if product else snap_product.get("category"),
        ),
        score=result.get("score"),
        band=result.get("band"),
        verdict=result.get("verdict"),
        is_partial=bool(result.get("is_partial")),
        penalties=_factors(result, "penalties"),
        positives=_factors(result, "positives"),
        scored_at=scored_at,
        verified=bool(product and product.verified),
    )
