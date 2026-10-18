"""Extraction evaluation harness (guide §7.6).

    python -m eval.run --prompt v1 --provider claude
    python -m eval.run --provider fake            # free smoke run used in CI

Each case in eval/dataset/*.json holds paths to three photos and the hand-labelled ground
truth (normalised per 100 g/ml). The harness runs the *real* pipeline — provider → schema
validation → normalisation → scoring — and reports per-field accuracy, hallucination rate,
ingredient F1, score error, failure rate, latency and cost. Results are appended to
eval/results.md; run it before merging any prompt or model change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.services.extraction.base import ExtractionError, VisionExtractor  # noqa: E402
from app.services.extraction.fake import FakeExtractor  # noqa: E402
from app.services.extraction.fallback import _build_one  # noqa: E402
from app.services.normalise.normaliser import normalise  # noqa: E402
from app.services.scoring import (  # noqa: E402
    DEFAULT_ADDITIVES_PATH,
    load_additive_table,
    parse_ingredients,
    score,
)
from eval.metrics import NUMERIC_FIELDS, EvalReport, ingredient_f1  # noqa: E402

DATASET = Path(__file__).parent / "dataset"
RESULTS = Path(__file__).parent / "results.md"
ROLES = ("front", "nutrition", "ingredients")


def load_cases(dataset: Path, only: str | None = None) -> list[dict[str, Any]]:
    cases = []
    for path in sorted(dataset.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        case.setdefault("id", path.stem)
        case["_dir"] = path.parent
        if only and only not in case["id"]:
            continue
        cases.append(case)
    return cases


def build_extractor(provider: str) -> VisionExtractor:
    if provider == "fake":
        return FakeExtractor()
    settings = Settings()  # reads ANTHROPIC_API_KEY / GEMINI_API_KEY etc. from env / .env
    return _build_one(provider, settings)


async def run_case(
    extractor: VisionExtractor,
    case: dict[str, Any],
    prompt: str,
    report: EvalReport,
    additives: Any,
) -> dict[str, Any]:
    report.cases += 1
    if isinstance(extractor, FakeExtractor):
        extractor.fixture = case.get("fake_fixture", "chocolate_biscuit")
        images = [b""] * 3
    else:
        images = [(case["_dir"] / case["images"][role]).read_bytes() for role in ROLES]

    expected = case["expected"]
    started = time.perf_counter()
    try:
        res = await extractor.extract(images, prompt)
    except ExtractionError as exc:
        report.failures += 1
        report.errors.append(f"{case['id']}: {exc}")
        return {"id": case["id"], "status": "FAILED", "error": str(exc)}
    report.latencies_ms.append(res.latency_ms or int((time.perf_counter() - started) * 1000))
    report.costs_usd.append(res.cost_usd)

    outcome = normalise(res.extraction)
    if outcome.needs_review:
        report.needs_review += 1
    predicted = outcome.nutrition.model_dump() if outcome.nutrition else {}
    report.add_nutrition(predicted, expected.get("nutrition", {}))
    report.ingredient_f1.append(
        ingredient_f1(res.extraction.ingredients, expected.get("ingredients", []))
    )

    result = score(
        outcome.nutrition,
        parse_ingredients(res.extraction.ingredients),
        additives,
        is_beverage=outcome.is_beverage,
        extra_additive_codes=res.extraction.additive_codes,
    )
    if "score" in expected:
        report.score_abs_error.append(abs(result.score - expected["score"]))
    if "band" in expected:
        report.band_match.append(result.band.value == expected["band"])

    diffs = {
        f: {"predicted": predicted.get(f), "expected": expected.get("nutrition", {}).get(f)}
        for f in NUMERIC_FIELDS
        if predicted.get(f) != expected.get("nutrition", {}).get(f)
    }
    return {
        "id": case["id"],
        "status": "NEEDS_REVIEW" if outcome.needs_review else "DONE",
        "score": result.score,
        "diffs": diffs,
    }


def to_markdown(args: argparse.Namespace, summary: dict[str, Any], model: str) -> str:
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = "\n".join(f"| {k} | {v} |" for k, v in summary.items())
    return f"\n## {when} — provider `{args.provider}` · model `{model}` · prompt `{args.prompt}`\n\n| Metric | Value |\n|---|---|\n{rows}\n"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--prompt", default="v1")
    parser.add_argument("--provider", default="fake", choices=["fake", "claude", "gemini"])
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--only", help="run cases whose id contains this text")
    parser.add_argument("--no-write", action="store_true", help="do not append to results.md")
    parser.add_argument(
        "--min-exact", type=float, default=0.0, help="exit 1 if exact accuracy is below this"
    )
    args = parser.parse_args()

    cases = load_cases(args.dataset, args.only)
    if not cases:
        print(f"No cases found in {args.dataset}")
        return 1
    extractor = build_extractor(args.provider)
    additives = load_additive_table(DEFAULT_ADDITIVES_PATH)
    report = EvalReport()
    details = []
    for case in cases:
        details.append(await run_case(extractor, case, args.prompt, report, additives))
        print(f"  {details[-1]['id']:<32} {details[-1]['status']}")

    summary = report.summary()
    print(json.dumps(summary, indent=2))
    for err in report.errors:
        print(f"  ! {err}")
    for d in details:
        if d.get("diffs"):
            print(f"  ~ {d['id']}: {json.dumps(d['diffs'])}")
    model = getattr(extractor, "model", args.provider)
    if not args.no_write:
        with RESULTS.open("a", encoding="utf-8") as fh:
            fh.write(to_markdown(args, summary, str(model)))
    return 0 if summary["numeric_exact_accuracy"] >= args.min_exact else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
