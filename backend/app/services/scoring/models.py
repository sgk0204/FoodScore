"""Value objects for the scoring engine.

The engine is a pure function over these types: no I/O, no clock, no randomness.
Same input always produces the same ScoreResult (ADR-1).
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Band(StrEnum):
    VERY_BAD = "VERY_BAD"
    BAD = "BAD"
    GOOD = "GOOD"
    VERY_GOOD = "VERY_GOOD"
    EXCELLENT = "EXCELLENT"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class Layer(StrEnum):
    NUTRIENT = "nutrient"
    INGREDIENT = "ingredient"
    PROCESSING = "processing"


class NutritionInput(BaseModel):
    """Nutrition normalised to per 100 g (foods) or per 100 ml (drinks).

    ``None`` means "not printed / not readable" and is never treated as zero by the
    caller; the engine decides how to handle missing values (partial score).
    """

    model_config = ConfigDict(frozen=True)

    energy_kcal: float | None = None
    sugars_g: float | None = None
    added_sugars_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    sat_fat_g: float | None = None
    trans_fat_g: float | None = None
    salt_g: float | None = None
    fibre_g: float | None = None
    protein_g: float | None = None

    CORE_FIELDS: ClassVar[tuple[str, ...]] = (
        "energy_kcal",
        "sugars_g",
        "fat_g",
        "sat_fat_g",
        "salt_g",
    )

    def core_present(self) -> int:
        return sum(1 for f in self.CORE_FIELDS if getattr(self, f) is not None)


class Ingredient(BaseModel):
    """One ingredient in label order. Sub-ingredients keep a reference to their parent."""

    model_config = ConfigDict(frozen=True)

    name: str  # lower-cased, whitespace-normalised
    raw: str  # as printed / as extracted
    parent: str | None = None
    position: int  # index of the top-level ingredient this belongs to (0 = first)


class Penalty(BaseModel):
    factor: str  # stable machine key, e.g. "sugar", "additive:INS 171", "palm_oil"
    label: str  # short human label, e.g. "High sugar"
    layer: Layer
    raw_points: float  # points lost inside its layer (0-100 scale)
    points: float  # weighted points: what this actually moved the final score
    reason: str  # plain-language explanation shown to the user
    code: str | None = None  # additive code, when applicable


class Positive(BaseModel):
    factor: str
    label: str
    layer: Layer
    raw_points: float
    points: float
    reason: str


class CapApplied(BaseModel):
    rule: str  # "trans_fat", "high_concern_additive", "partial"
    cap: int
    reason: str


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    band: Band
    verdict: str
    is_partial: bool
    nutrient_score: float | None  # None when no nutrition table was available
    ingredient_score: float
    processing_score: float
    nova: int
    penalties: list[Penalty]  # sorted by weighted points, descending
    positives: list[Positive]
    caps_applied: list[CapApplied]
    flagged_ingredients: list[str]  # raw ingredient strings that triggered a rule
    unrated_additives: list[str]  # codes not found in additives_ref (logged for review)
    scoring_version: str
