"""Synthetic test photos: distinct patterns (so duplicate detection passes) and real barcodes."""

from __future__ import annotations

import io
import random

import zxingcpp
from PIL import Image, ImageDraw


def photo(seed: int, size: tuple[int, int] = (800, 600), barcode: str | None = None) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", size, (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    draw = ImageDraw.Draw(img)
    for _ in range(40):
        x0, y0 = rng.randint(0, size[0]), rng.randint(0, size[1])
        x1, y1 = x0 + rng.randint(20, 300), y0 + rng.randint(20, 300)
        draw.rectangle(
            (x0, y0, x1, y1), fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        )
    if barcode:
        code = zxingcpp.create_barcode(barcode, zxingcpp.BarcodeFormat.EAN13).to_image(scale=3)
        mv = memoryview(code)
        bar = Image.frombytes("L", (mv.shape[1], mv.shape[0]), mv.tobytes())
        pad = Image.new("L", (bar.width + 60, bar.height + 60), 255)
        pad.paste(bar, (30, 30))
        img.paste(pad.convert("RGB"), (20, 20))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def photo_set(base_seed: int = 1, barcode: str | None = None) -> dict[str, tuple[str, bytes, str]]:
    return {
        "front": ("front.jpg", photo(base_seed, barcode=barcode), "image/jpeg"),
        "nutrition": ("nutrition.jpg", photo(base_seed + 100), "image/jpeg"),
        "ingredients": ("ingredients.jpg", photo(base_seed + 200), "image/jpeg"),
    }
