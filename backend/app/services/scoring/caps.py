"""Hard caps (guide §6.4): override rules applied after the weighted score is rounded."""

from __future__ import annotations

from app.services.scoring import thresholds as t
from app.services.scoring.models import CapApplied, NutritionInput


def caps_for(
    nutrition: NutritionInput | None,
    *,
    has_pho: bool,
    has_high_concern_additive: bool,
    is_partial: bool,
) -> list[CapApplied]:
    caps: list[CapApplied] = []
    trans = nutrition.trans_fat_g if nutrition else None
    if has_pho or (trans is not None and trans > t.TRANS_FAT_LIMIT_G):
        why = (
            "Contains partially hydrogenated oil (industrial trans fat)"
            if has_pho
            else f"Trans fat {trans:g} g is above {t.TRANS_FAT_LIMIT_G:g} g"
        )
        caps.append(CapApplied(rule="trans_fat", cap=t.CAP_TRANS_FAT, reason=why))
    if has_high_concern_additive:
        caps.append(
            CapApplied(
                rule="high_concern_additive",
                cap=t.CAP_HIGH_CONCERN_ADDITIVE,
                reason="Contains a high-concern additive",
            )
        )
    if is_partial:
        caps.append(
            CapApplied(
                rule="partial",
                cap=t.CAP_PARTIAL,
                reason="Nutrition table missing or incomplete — partial score",
            )
        )
    return caps


def apply_caps(score: int, caps: list[CapApplied]) -> int:
    for cap in caps:
        score = min(score, cap.cap)
    return max(0, min(100, score))
