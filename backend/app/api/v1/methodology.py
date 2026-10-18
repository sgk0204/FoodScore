"""Public scoring methodology (F10), generated from the engine's own constants.

Because the page is built from the same constants the engine uses, it cannot drift from the
actual scoring rules.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import ServicesDep
from app.services.normalise import units
from app.services.scoring import thresholds as t

router = APIRouter(tags=["methodology"])


def _thresholds(rules: tuple[t.Threshold, ...]) -> list[dict[str, Any]]:
    return [
        {
            "factor": r.factor,
            "name": r.name,
            "unit": r.unit,
            "low": r.low,
            "high": r.high,
            "max_penalty": r.max_penalty,
        }
        for r in rules
    ]


@router.get("/methodology")
async def methodology(svc: ServicesDep, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {
        "scoring_version": t.SCORING_VERSION,
        "formula": "round_half_up(0.6 × NutrientScore + 0.3 × IngredientScore + 0.1 × ProcessingScore), "
        "then hard caps, clamp 0–100, map to band",
        "weights": {
            "nutrient": t.W_NUTRIENT,
            "ingredient": t.W_INGREDIENT,
            "processing": t.W_PROCESSING,
        },
        "partial_weights": {
            "ingredient": round(t.W_INGREDIENT_PARTIAL, 4),
            "processing": round(t.W_PROCESSING_PARTIAL, 4),
        },
        "nutrient_thresholds": {
            "food_per_100g": _thresholds(t.FOOD_THRESHOLDS),
            "drink_per_100ml": _thresholds(t.DRINK_THRESHOLDS),
        },
        "interpolation": "≤ low costs nothing; > high costs the maximum; linear in between",
        "bonuses": [
            {"factor": b.factor, "tiers": [{"min_g": m, "points": p} for m, p in b.tiers]}
            for b in t.BONUSES
        ],
        "nova_scores": t.NOVA_SCORE,
        "ingredient_penalties": {
            "high_concern_additive": t.ADDITIVE_PENALTY["high"],
            "moderate_concern_additive": t.ADDITIVE_PENALTY["moderate"],
            "low_concern_additive": t.ADDITIVE_PENALTY["low"],
            "partially_hydrogenated_oil": t.PENALTY_PHO,
            "palm_oil": t.PENALTY_PALM_OIL,
            "added_sugar_in_first_3": t.PENALTY_ADDED_SUGAR_TOP3,
            "refined_flour_first": t.PENALTY_REFINED_FLOUR_FIRST,
            "unknown_additive": 0,
        },
        "caps": [
            {
                "rule": "trans_fat",
                "cap": t.CAP_TRANS_FAT,
                "when": f"trans fat > {t.TRANS_FAT_LIMIT_G} g/100 g or any partially hydrogenated oil",
            },
            {
                "rule": "high_concern_additive",
                "cap": t.CAP_HIGH_CONCERN_ADDITIVE,
                "when": "contains a high-concern additive",
            },
            {
                "rule": "partial",
                "cap": t.CAP_PARTIAL,
                "when": "nutrition table missing or incomplete",
            },
        ],
        "bands": [
            {"max": upper, "band": band.value, "label": band.label} for upper, band in t.BANDS
        ],
        "rounding": "Round half up to an integer first, then map to a band (60.5 → 61 → Very Good).",
        "parsing_rules": {
            "less_than": "'<x' is scored as x/2",
            "zero_words": "Nil, None, Traces, -, – → 0",
            "decimal_comma": "5,2 → 5.2",
            "kj_to_kcal": f"kJ ÷ {units.KJ_PER_KCAL}",
            "sodium_to_salt": f"salt g = sodium g × {units.SALT_PER_SODIUM}",
        },
        "sources": [
            {"name": "Nutri-Score", "url": "https://www.santepubliquefrance.fr/en/nutri-score"},
            {
                "name": "UK FSA front-of-pack guidance",
                "url": "https://www.gov.uk/government/publications/front-of-pack-nutrition-labelling-guidance",
            },
            {"name": "NOVA classification", "url": "https://www.fao.org/3/ca5644en/ca5644en.pdf"},
            {
                "name": "EFSA food additives",
                "url": "https://www.efsa.europa.eu/en/topics/topic/food-additives",
            },
            {"name": "FSSAI", "url": "https://www.fssai.gov.in/"},
            {
                "name": "IARC Monographs",
                "url": "https://monographs.iarc.who.int/agents-classified-by-the-iarc/",
            },
        ],
        "additives": [
            {
                "code": a.code,
                "name": a.name,
                "risk_tier": a.risk_tier,
                "source_url": a.source_url,
                "notes": a.notes,
            }
            for a in sorted(
                svc.additives.by_code.values(),
                key=lambda a: ({"high": 0, "moderate": 1, "low": 2}[a.risk_tier], a.code),
            )
        ],
        "disclaimer": "Weights and additive tiers are documented product decisions based on public "
        "frameworks, not scientific facts. For general information only. Not medical or dietary advice.",
    }
