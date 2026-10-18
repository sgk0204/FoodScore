"""Live check of the configured AI provider with a synthetic label (makes ONE real API call).

    cd backend
    python scripts/check_provider.py              # uses LLM_PROVIDER from .env / environment
    python scripts/check_provider.py --provider gemini --model gemini-3.8-flash

Reads the API key from the environment or a `.env` file (repo root or backend/) — the key is
never printed. Draws three label photos with known values (the guide's chocolate cream
biscuit), runs extraction → normalisation → scoring, and compares against the expected answer.
Exit code 0 means the provider works end to end.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")  # not used, but required
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "check-provider-script-not-a-real-secret")

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.services.extraction.base import ExtractionError
from app.services.extraction.fallback import _build_one
from app.services.normalise.normaliser import normalise
from app.services.scoring import (
    DEFAULT_ADDITIVES_PATH,
    load_additive_table,
    parse_ingredients,
    score,
)

EXPECTED = {
    "energy_kcal": 480,
    "sugars_g": 30,
    "fat_g": 22,
    "sat_fat_g": 10,
    "salt_g": 0.6,
    "protein_g": 6,
}


def _panel(lines: list[tuple[str, int]], size: tuple[int, int] = (900, 700)) -> bytes:
    img = Image.new("RGB", size, (250, 247, 240))
    draw = ImageDraw.Draw(img)
    y = 40
    for text, font_size in lines:
        font = ImageFont.load_default(size=font_size)
        draw.text((50, y), text, fill=(20, 20, 20), font=font)
        y += int(font_size * 1.6)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def synthetic_label() -> list[bytes]:
    front = _panel(
        [("ACME FOODS", 40), ("Choco Cream", 64), ("Biscuit", 64), ("Net wt. 120 g", 30)]
    )
    rows = [
        ("Energy", "480 kcal"),
        ("Protein", "6 g"),
        ("Carbohydrate", "64 g"),
        ("  of which Total Sugars", "30 g"),
        ("  of which Added Sugars", "28 g"),
        ("Total Fat", "22 g"),
        ("  Saturated Fat", "10 g"),
        ("  Trans Fat", "0.1 g"),
        ("Dietary Fibre", "2 g"),
        ("Sodium", "240 mg"),
    ]
    nutrition = _panel(
        [("NUTRITION INFORMATION", 34), ("Per 100 g", 30)]
        + [(f"{name:<28}{value:>10}", 28) for name, value in rows],
        size=(900, 900),
    )
    ingredients = _panel(
        [
            ("INGREDIENTS:", 34),
            ("Whole wheat flour, Palm oil, Cocoa solids,", 28),
            ("Sugar, Emulsifier (INS 322),", 28),
            ("Raising agent (INS 503),", 28),
            ("Artificial flavour (chocolate).", 28),
        ]
    )
    return [front, nutrition, ingredients]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--provider", choices=["gemini", "claude"], help="defaults to LLM_PROVIDER")
    parser.add_argument("--model", help="override GEMINI_MODEL / CLAUDE_MODEL")
    args = parser.parse_args()

    overrides: dict[str, str] = {}
    if args.provider:
        overrides["llm_provider"] = args.provider
    try:
        settings = Settings(**overrides)  # type: ignore[arg-type]
    except ValueError as exc:
        missing = (
            "GEMINI_API_KEY"
            if "GEMINI" in str(exc)
            else "ANTHROPIC_API_KEY"
            if "ANTHROPIC" in str(exc)
            else None
        )
        if missing:
            print(f"{missing} is not set. Add it to the .env file in the repo root:  {missing}=...")
            return 2
        raise
    provider = settings.llm_provider
    if provider == "fake":
        print(
            "LLM_PROVIDER is 'fake' — pass --provider gemini (or claude) to test a real provider."
        )
        return 2
    if args.model:
        settings = settings.model_copy(update={f"{provider}_model": args.model})
    model = getattr(settings, f"{provider}_model")
    print(f"Provider: {provider} · model: {model} · prompt: {settings.prompt_version}")

    extractor = _build_one(provider, settings)
    try:
        result = await extractor.extract(synthetic_label(), settings.prompt_version)
    except ExtractionError as exc:
        print(f"\nFAILED: {exc}")
        cause = exc.__cause__
        if cause is not None:
            print(f"  cause: {type(cause).__name__}: {str(cause)[:400]}")
        if "404" in str(exc) and provider == "gemini":
            print("  The model name may be wrong or retired. List available models with:")
            print(
                '  python -c "from google import genai; [print(m.name) for m in genai.Client().models.list()]"'
            )
        return 1

    ex = result.extraction
    outcome = normalise(ex, review_threshold=settings.review_confidence_threshold)
    n = outcome.nutrition.model_dump() if outcome.nutrition else {}
    print(
        f"\nRead in {result.latency_ms} ms · {result.input_tokens}+{result.output_tokens} tokens · ≈ ${result.cost_usd:.4f}"
    )
    print(
        f"Product: {ex.product_name!r} by {ex.brand!r} · basis={ex.basis} · food label={ex.is_food_label}"
    )
    print(f"Ingredients: {ex.ingredients}")
    ok = True
    print("\nField          expected   read")
    for field, want in EXPECTED.items():
        got = n.get(field)
        match = got is not None and abs(got - want) <= 0.011
        ok &= match
        print(f"  {field:<12} {want:>8}   {got!s:<8} {'✓' if match else '✗'}")

    result_score = score(
        outcome.nutrition,
        parse_ingredients(ex.ingredients),
        load_additive_table(DEFAULT_ADDITIVES_PATH),
        is_beverage=outcome.is_beverage,
        extra_additive_codes=ex.additive_codes,
    )
    print(f"\nScore: {result_score.score} ({result_score.band.label}) — expected 39 (Bad)")
    if outcome.needs_review:
        print(f"Would go to review: {[i.message for i in outcome.issues]}")
    print(
        "\nRESULT:",
        "PASS — provider works end to end" if ok else "CHECK — some values were misread",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
