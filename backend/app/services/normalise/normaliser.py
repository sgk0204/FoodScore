"""Turn a raw LLM Extraction into per-100 g/ml nutrition plus a review decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas.extraction import Extraction, NutrientValue
from app.services.normalise import sanity
from app.services.normalise.units import parse_amount, sodium_to_salt, to_grams, to_kcal
from app.services.scoring.models import NutritionInput

# Extraction field → NutritionInput field
FIELD_MAP: dict[str, str] = {
    "energy": "energy_kcal",
    "sugars": "sugars_g",
    "added_sugars": "added_sugars_g",
    "carbohydrates": "carbs_g",
    "total_fat": "fat_g",
    "saturated_fat": "sat_fat_g",
    "trans_fat": "trans_fat_g",
    "sodium_or_salt": "salt_g",
    "fibre": "fibre_g",
    "protein": "protein_g",
}
CORE_EXTRACTION_FIELDS = ("energy", "sugars", "total_fat", "saturated_fat", "sodium_or_salt")


@dataclass(slots=True)
class ReviewIssue:
    field: str
    code: str
    message: str


@dataclass(slots=True)
class NormalisationOutcome:
    nutrition: NutritionInput | None
    basis: Literal["per_100g", "per_100ml", "per_serving", "unknown"]
    is_beverage: bool
    confidence: float
    field_confidence: dict[str, float]
    issues: list[ReviewIssue] = field(default_factory=list)
    needs_review: bool = False
    nutrition_unreadable: bool = False


def _read(nv: NutrientValue) -> tuple[float, str | None] | None:
    parsed = parse_amount(nv.raw) if nv.raw else None
    if parsed is not None:
        value, unit = parsed
        return value, unit or nv.unit
    if nv.value is not None:
        return nv.value, nv.unit
    return None


def normalise(ex: Extraction, *, review_threshold: float = 0.7) -> NormalisationOutcome:
    issues: list[ReviewIssue] = []
    values: dict[str, float] = {}
    confidence: dict[str, float] = {}

    for ex_field, out_field in FIELD_MAP.items():
        nv: NutrientValue = getattr(ex, ex_field)
        read = _read(nv)
        if read is None:
            continue
        value, unit = read
        if ex_field == "energy":
            value = to_kcal(value, unit)
        else:
            value = to_grams(value, unit)
            if ex_field == "sodium_or_salt":
                # Sodium in mg is the common Indian format; an explicit label wins.
                is_sodium = ex.salt_label == "sodium" or (ex.salt_label is None and unit == "mg")
                if is_sodium:
                    value = sodium_to_salt(value)
        values[out_field] = value
        confidence[out_field] = nv.confidence

    is_beverage = ex.category_guess == "beverage" or ex.basis == "per_100ml"
    basis = ex.basis
    if basis == "per_serving":
        if ex.serving_size_g and ex.serving_size_g > 0:
            factor = 100.0 / ex.serving_size_g
            values = {k: v * factor for k, v in values.items()}
            basis = "per_100ml" if is_beverage else "per_100g"
        elif values:
            issues.append(
                ReviewIssue(
                    "serving_size_g",
                    "serving_size_missing",
                    "Only per-serving values are printed and the serving size is unreadable",
                )
            )
    elif basis == "unknown" and values:
        issues.append(
            ReviewIssue("basis", "basis_unknown", "Could not tell whether values are per 100 g")
        )
        basis = "per_100ml" if is_beverage else "per_100g"

    rounded = {k: round(v, 3) for k, v in values.items()}
    nutrition = NutritionInput(**rounded) if rounded else None

    if nutrition is not None:
        for s in sanity.check(nutrition):
            issues.append(ReviewIssue(s.field, s.code, s.message))

    core_conf = [
        confidence[FIELD_MAP[f]] for f in CORE_EXTRACTION_FIELDS if FIELD_MAP[f] in confidence
    ]
    overall = sum(core_conf) / len(core_conf) if core_conf else 0.0
    overall = max(0.0, overall - 0.15 * len(issues))
    low_fields = [f for f, c in confidence.items() if c < review_threshold]
    for f in low_fields:
        issues.append(ReviewIssue(f, "low_confidence", "The model was unsure about this value"))

    # An empty table with legibility complaints about the nutrition photo is unreadable,
    # not "missing": we must not score it (user story 4).
    nutrition_unreadable = nutrition is None and any(
        i.image == "nutrition" for i in ex.legibility_issues
    )

    needs_review = bool(issues) or (nutrition is not None and overall < review_threshold)
    return NormalisationOutcome(
        nutrition=nutrition,
        basis=basis,
        is_beverage=is_beverage,
        confidence=round(overall, 3) if nutrition is not None else 0.0,
        field_confidence={k: round(v, 3) for k, v in confidence.items()},
        issues=issues,
        needs_review=needs_review,
        nutrition_unreadable=nutrition_unreadable,
    )
