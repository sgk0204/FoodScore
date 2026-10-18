"""Scoring constants (guide §6). Every number here is a documented product decision.

Nutrient thresholds follow the UK FSA front-of-pack traffic-light cut-offs (per 100 g for
foods, per 100 ml for drinks). Weights, caps and bands are FoodScore's own choices and are
published on the methodology page.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.scoring.models import Band

SCORING_VERSION = "1.0.0"

W_NUTRIENT = 0.6
W_INGREDIENT = 0.3
W_PROCESSING = 0.1

# Weights used when no nutrition table exists: ingredient and processing keep their
# relative proportions (0.3 : 0.1).
W_INGREDIENT_PARTIAL = W_INGREDIENT / (W_INGREDIENT + W_PROCESSING)
W_PROCESSING_PARTIAL = W_PROCESSING / (W_INGREDIENT + W_PROCESSING)


@dataclass(frozen=True, slots=True)
class Threshold:
    field: str  # attribute on NutritionInput
    factor: str  # stable key used in penalties
    name: str  # human name used in reasons
    unit: str
    low: float  # value <= low costs nothing (inclusive)
    high: float  # value > high costs max_penalty (exclusive)
    max_penalty: float


FOOD_THRESHOLDS: tuple[Threshold, ...] = (
    Threshold("sugars_g", "sugar", "Sugar", "g", 5.0, 22.5, 30.0),
    Threshold("sat_fat_g", "sat_fat", "Saturated fat", "g", 1.5, 5.0, 25.0),
    Threshold("salt_g", "salt", "Salt", "g", 0.3, 1.5, 25.0),
    Threshold("fat_g", "fat", "Total fat", "g", 3.0, 17.5, 10.0),
    Threshold("energy_kcal", "energy", "Energy", "kcal", 400.0, 600.0, 10.0),
)

DRINK_THRESHOLDS: tuple[Threshold, ...] = (
    Threshold("sugars_g", "sugar", "Sugar", "g", 2.5, 11.25, 30.0),
    Threshold("sat_fat_g", "sat_fat", "Saturated fat", "g", 0.75, 2.5, 25.0),
    Threshold("salt_g", "salt", "Salt", "g", 0.3, 0.75, 25.0),
    Threshold("fat_g", "fat", "Total fat", "g", 1.5, 8.75, 10.0),
    Threshold("energy_kcal", "energy", "Energy", "kcal", 20.0, 80.0, 10.0),
)


@dataclass(frozen=True, slots=True)
class BonusRule:
    field: str
    factor: str
    name: str
    tiers: tuple[tuple[float, float], ...]  # (min value inclusive, bonus), highest first


BONUSES: tuple[BonusRule, ...] = (
    BonusRule("fibre_g", "fibre", "Fibre", ((6.0, 10.0), (3.0, 5.0))),
    BonusRule("protein_g", "protein", "Protein", ((10.0, 8.0), (5.0, 4.0))),
)

NOVA_SCORE: dict[int, float] = {1: 100.0, 2: 80.0, 3: 60.0, 4: 20.0}

# Ingredient-layer penalties (raw points, 0-100 scale)
ADDITIVE_PENALTY: dict[str, float] = {"high": 30.0, "moderate": 15.0, "low": 5.0}
PENALTY_PHO = 30.0
PENALTY_PALM_OIL = 10.0
PENALTY_ADDED_SUGAR_TOP3 = 10.0
PENALTY_REFINED_FLOUR_FIRST = 5.0

# Hard caps (§6.4)
CAP_TRANS_FAT = 40
TRANS_FAT_LIMIT_G = 0.2
CAP_HIGH_CONCERN_ADDITIVE = 50
CAP_PARTIAL = 60

# Bands (§6.5): upper bound inclusive
BANDS: tuple[tuple[int, Band], ...] = (
    (20, Band.VERY_BAD),
    (40, Band.BAD),
    (60, Band.GOOD),
    (80, Band.VERY_GOOD),
    (100, Band.EXCELLENT),
)


def band_for(score: int) -> Band:
    for upper, band in BANDS:
        if score <= upper:
            return band
    return Band.EXCELLENT
