"""Deterministic scoring engine. Public API: ``score`` and the value objects."""

from app.services.scoring.additives import (
    DEFAULT_ADDITIVES_PATH,
    AdditiveRef,
    AdditiveTable,
    load_additive_table,
)
from app.services.scoring.engine import score
from app.services.scoring.ingredients import parse_ingredients
from app.services.scoring.models import (
    Band,
    Ingredient,
    NutritionInput,
    Penalty,
    Positive,
    ScoreResult,
)
from app.services.scoring.thresholds import SCORING_VERSION, band_for

__all__ = [
    "DEFAULT_ADDITIVES_PATH",
    "SCORING_VERSION",
    "AdditiveRef",
    "AdditiveTable",
    "Band",
    "Ingredient",
    "NutritionInput",
    "Penalty",
    "Positive",
    "ScoreResult",
    "band_for",
    "load_additive_table",
    "parse_ingredients",
    "score",
]
