"""Post-LLM sanity checks (guide §7.4). They never change values — they flag them.

A flagged field lowers confidence and routes the scan to NEEDS_REVIEW so the user can
confirm or fix it. Typical catch: a misread decimal ("52" instead of "5.2", edge case 16).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.scoring.models import NutritionInput

MACRO_SUM_LIMIT_G = 105.0
ENERGY_TOLERANCE = 0.20
MAX_SALT_G = 50.0
MAX_ENERGY_KCAL = 900.0
MAX_GRAMS = 100.0


@dataclass(frozen=True, slots=True)
class SanityIssue:
    field: str
    code: str
    message: str


def check(n: NutritionInput) -> list[SanityIssue]:
    issues: list[SanityIssue] = []

    def flag(field: str, code: str, message: str) -> None:
        issues.append(SanityIssue(field, code, message))

    # Plausible ranges
    for field in (
        "sugars_g",
        "added_sugars_g",
        "carbs_g",
        "fat_g",
        "sat_fat_g",
        "trans_fat_g",
        "fibre_g",
        "protein_g",
    ):
        value = getattr(n, field)
        if value is not None and (value < 0 or value > MAX_GRAMS):
            flag(field, "out_of_range", f"{value:g} g per 100 is not physically possible")
    if n.salt_g is not None and (n.salt_g < 0 or n.salt_g > MAX_SALT_G):
        flag("salt_g", "out_of_range", f"Salt {n.salt_g:g} g per 100 is implausible")
    if n.energy_kcal is not None and (n.energy_kcal < 0 or n.energy_kcal > MAX_ENERGY_KCAL):
        flag("energy_kcal", "out_of_range", f"Energy {n.energy_kcal:g} kcal per 100 is implausible")

    # Macro sum
    parts = [n.fat_g, n.carbs_g, n.protein_g, n.fibre_g]
    if sum(1 for p in parts if p is not None) >= 2:
        total = sum(p for p in parts if p is not None)
        if total > MACRO_SUM_LIMIT_G:
            flag(
                "macros",
                "macro_sum",
                f"Fat + carbs + protein + fibre = {total:g} g, more than {MACRO_SUM_LIMIT_G:g} g",
            )

    # Sub-totals (likely decimal errors)
    if n.sugars_g is not None and n.carbs_g is not None and n.sugars_g > n.carbs_g + 0.5:
        flag("sugars_g", "subtotal", "Sugars are higher than total carbohydrates")
    if n.sat_fat_g is not None and n.fat_g is not None and n.sat_fat_g > n.fat_g + 0.1:
        flag("sat_fat_g", "subtotal", "Saturated fat is higher than total fat")
    if n.trans_fat_g is not None and n.fat_g is not None and n.trans_fat_g > n.fat_g + 0.1:
        flag("trans_fat_g", "subtotal", "Trans fat is higher than total fat")
    if (
        n.added_sugars_g is not None
        and n.sugars_g is not None
        and n.added_sugars_g > n.sugars_g + 0.5
    ):
        flag("added_sugars_g", "subtotal", "Added sugars are higher than total sugars")

    # Energy cross-check: kcal ≈ 4P + 4C + 9F + 2 fibre
    if None not in (n.energy_kcal, n.protein_g, n.carbs_g, n.fat_g):
        assert n.energy_kcal is not None and n.protein_g is not None
        assert n.carbs_g is not None and n.fat_g is not None
        expected = 4 * n.protein_g + 4 * n.carbs_g + 9 * n.fat_g + 2 * (n.fibre_g or 0)
        if expected > 20 and abs(n.energy_kcal - expected) > ENERGY_TOLERANCE * expected:
            flag(
                "energy_kcal",
                "energy_mismatch",
                f"Energy {n.energy_kcal:g} kcal does not match macros (≈{expected:.0f} kcal)",
            )
    return issues
