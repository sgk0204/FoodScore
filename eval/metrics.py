"""Scoring functions for the extraction eval. Pure functions, unit-tested in test_metrics.py."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

NUMERIC_FIELDS = (
    "energy_kcal",
    "sugars_g",
    "added_sugars_g",
    "carbs_g",
    "fat_g",
    "sat_fat_g",
    "trans_fat_g",
    "salt_g",
    "fibre_g",
    "protein_g",
)
EXACT_TOLERANCE = 0.011  # values are printed to 1–2 decimals; allow float noise only
CLOSE_RELATIVE = 0.05


def _norm_ingredient(text: str) -> str:
    text = text.lower().split(">")[-1]
    text = re.sub(r"\(.*?\)|\[.*?\]|\d+(\.\d+)?\s*%", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def ingredient_f1(predicted: Iterable[str], expected: Iterable[str]) -> float:
    p = {_norm_ingredient(i) for i in predicted} - {""}
    e = {_norm_ingredient(i) for i in expected} - {""}
    if not p and not e:
        return 1.0
    if not p or not e:
        return 0.0
    tp = len(p & e)
    precision, recall = tp / len(p), tp / len(e)
    return 0.0 if tp == 0 else 2 * precision * recall / (precision + recall)


@dataclass
class FieldStats:
    total: int = 0  # cases where the label prints this field
    exact: int = 0
    close: int = 0  # within 5 %
    missing: int = 0  # printed, but extractor returned null
    hallucinated: int = 0  # not printed, but extractor returned a value
    absent_cases: int = 0  # cases where the label does not print this field

    def add(self, predicted: float | None, expected: float | None) -> None:
        if expected is None:
            self.absent_cases += 1
            if predicted is not None:
                self.hallucinated += 1
            return
        self.total += 1
        if predicted is None:
            self.missing += 1
            return
        if abs(predicted - expected) <= EXACT_TOLERANCE:
            self.exact += 1
            self.close += 1
        elif expected != 0 and abs(predicted - expected) / abs(expected) <= CLOSE_RELATIVE:
            self.close += 1


@dataclass
class EvalReport:
    fields: dict[str, FieldStats] = field(
        default_factory=lambda: {f: FieldStats() for f in NUMERIC_FIELDS}
    )
    ingredient_f1: list[float] = field(default_factory=list)
    score_abs_error: list[float] = field(default_factory=list)
    band_match: list[bool] = field(default_factory=list)
    latencies_ms: list[int] = field(default_factory=list)
    costs_usd: list[float] = field(default_factory=list)
    cases: int = 0
    failures: int = 0
    needs_review: int = 0
    errors: list[str] = field(default_factory=list)

    def add_nutrition(
        self, predicted: Mapping[str, float | None], expected: Mapping[str, float | None]
    ) -> None:
        for f in NUMERIC_FIELDS:
            self.fields[f].add(predicted.get(f), expected.get(f))

    @property
    def numeric_exact_accuracy(self) -> float:
        total = sum(s.total for s in self.fields.values())
        return sum(s.exact for s in self.fields.values()) / total if total else 0.0

    @property
    def numeric_close_accuracy(self) -> float:
        total = sum(s.total for s in self.fields.values())
        return sum(s.close for s in self.fields.values()) / total if total else 0.0

    @property
    def hallucination_rate(self) -> float:
        absent = sum(s.absent_cases for s in self.fields.values())
        return sum(s.hallucinated for s in self.fields.values()) / absent if absent else 0.0

    def summary(self) -> dict[str, float | int]:
        lat = sorted(self.latencies_ms)
        p95 = lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else 0
        return {
            "cases": self.cases,
            "numeric_exact_accuracy": round(self.numeric_exact_accuracy, 4),
            "numeric_within_5pct": round(self.numeric_close_accuracy, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "ingredient_f1": round(statistics.fmean(self.ingredient_f1), 4)
            if self.ingredient_f1
            else 0.0,
            "score_mae": round(statistics.fmean(self.score_abs_error), 2)
            if self.score_abs_error
            else 0.0,
            "band_accuracy": round(sum(self.band_match) / len(self.band_match), 4)
            if self.band_match
            else 0.0,
            "failure_rate": round(self.failures / self.cases, 4) if self.cases else 0.0,
            "needs_review_rate": round(self.needs_review / self.cases, 4) if self.cases else 0.0,
            "latency_avg_ms": round(statistics.fmean(lat)) if lat else 0,
            "latency_p95_ms": p95,
            "cost_per_scan_usd": round(statistics.fmean(self.costs_usd), 5)
            if self.costs_usd
            else 0.0,
        }
