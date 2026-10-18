"""Barcode detection on the front image — the cache key for repeat scans (ADR-3).

Only retail EAN/UPC symbologies are accepted, and the GS1 check digit is verified so a
misread never pollutes the shared cache.
"""

from __future__ import annotations

from typing import Any

import structlog
from PIL import Image

log = structlog.get_logger(__name__)

zxingcpp: Any
try:  # zxing-cpp ships wheels for all major platforms; degrade gracefully if missing.
    import zxingcpp
except ImportError:  # pragma: no cover
    zxingcpp = None


def gs1_check_digit_ok(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalise_barcode(code: str) -> str | None:
    code = code.strip()
    if len(code) == 12 and code.isdigit():  # UPC-A → EAN-13
        code = "0" + code
    return code if gs1_check_digit_ok(code) else None


def detect_barcode(*images: Image.Image) -> str | None:
    if zxingcpp is None:
        return None
    formats = (
        zxingcpp.BarcodeFormat.EAN13,
        zxingcpp.BarcodeFormat.EAN8,
        zxingcpp.BarcodeFormat.UPCA,
        zxingcpp.BarcodeFormat.UPCE,
    )
    for img in images:
        try:
            results = zxingcpp.read_barcodes(img, formats=formats)
        except Exception:
            log.warning("barcode_decode_error", exc_info=True)
            continue
        for r in results:
            code = normalise_barcode(r.text)
            if code:
                return code
    return None
