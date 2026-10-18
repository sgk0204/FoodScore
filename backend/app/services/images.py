"""Server-side image security and preparation (edge cases 4, 6, 7, 9, 45).

Every upload is: size-checked → magic-byte checked → fully decoded by Pillow → EXIF
orientation applied → resized → re-encoded as a fresh JPEG with *no* metadata. Re-encoding
throws away anything that is not pixels (embedded scripts, GPS, camera serials).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard

ROLES = ("front", "nutrition", "ingredients")

_MAGIC: tuple[tuple[bytes, int, str], ...] = (
    (b"\xff\xd8\xff", 0, "jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"WEBP", 8, "webp"),
)
_HEIC_BRANDS = (b"heic", b"heix", b"mif1", b"msf1", b"hevc")


@dataclass(frozen=True, slots=True)
class PreparedImage:
    role: str
    data: bytes  # clean JPEG
    width: int
    height: int
    dhash: int
    image: Image.Image  # decoded RGB copy, for barcode detection


def sniff(data: bytes) -> str | None:
    for magic, offset, kind in _MAGIC:
        if data[offset : offset + len(magic)] == magic:
            if kind == "webp" and data[:4] != b"RIFF":
                continue
            return kind
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "heic"
    return None


def dhash(img: Image.Image, size: int = 8) -> int:
    """Difference hash: robust perceptual fingerprint for duplicate detection."""
    small = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = small.tobytes()  # mode "L": one byte per pixel
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | int(left > right)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def prepare(role: str, data: bytes, *, max_bytes: int, max_px: int) -> PreparedImage:
    if not data:
        raise AppError(
            422, "empty-image", "Empty image", f"The {role} photo is empty.", retake=[role]
        )
    if len(data) > max_bytes:
        raise AppError(
            413,
            "image-too-large",
            "Image too large",
            f"The {role} photo is over {max_bytes // (1024 * 1024)} MB after compression.",
            retake=[role],
        )
    kind = sniff(data)
    if kind == "heic":
        raise AppError(
            415,
            "unsupported-image",
            "HEIC images must be converted",
            "Please upload JPEG, PNG or WebP. The app converts iPhone photos automatically.",
            retake=[role],
        )
    if kind is None:
        raise AppError(
            415,
            "unsupported-image",
            "Unsupported file type",
            f"The {role} file is not a JPEG, PNG or WebP image.",
            retake=[role],
        )
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # structural check
        decoded = Image.open(io.BytesIO(data))
        decoded.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise AppError(
            415,
            "unsupported-image",
            "Corrupt image",
            f"The {role} photo could not be decoded.",
            retake=[role],
        ) from exc

    oriented = ImageOps.exif_transpose(decoded)  # apply rotation *before* metadata is dropped
    img: Image.Image = oriented.convert("RGB")
    img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)  # no exif= → metadata stripped
    return PreparedImage(
        role=role,
        data=out.getvalue(),
        width=img.width,
        height=img.height,
        dhash=dhash(img),
        image=img,
    )


def find_duplicates(images: list[PreparedImage], threshold: int = 4) -> list[str]:
    """Roles whose photo is (nearly) identical to an earlier one (edge case 4)."""
    dupes: list[str] = []
    for i, a in enumerate(images):
        for b in images[:i]:
            if hamming(a.dhash, b.dhash) <= threshold:
                dupes.append(a.role)
                break
    return dupes
