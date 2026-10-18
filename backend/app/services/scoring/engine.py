"""The FoodScore scoring engine (guide §6).

    Final = round_half_up(0.6 × NutrientScore + 0.3 × IngredientScore + 0.1 × ProcessingScore)
            → hard caps → clamp 0–100 → band

Pure function, no I/O: the additive table is passed in. Every penalty records both its raw
points (inside its layer) and its weighted points (what it actually moved the final score),
so the UI can rank reasons by real impact.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.services.scoring import thresholds as t
from app.services.scoring.additives import AdditiveTable, normalise_code
from app.services.scoring.caps import apply_caps, caps_for
from app.services.scoring.ingredients import (
    classify_nova,
    is_added_sugar,
    is_palm,
    is_pho,
    is_refined_flour,
)
from app.services.scoring.models import (
    Band,
    Ingredient,
    Layer,
    NutritionInput,
    Penalty,
    Positive,
    ScoreResult,
)


def interpolate(value: float, low: float, high: float, max_pen: float) -> float:
    """0 at or below ``low`` (inclusive), ``max_pen`` above ``high`` (exclusive), linear between."""
    if value <= low:
        return 0.0
    if value > high:
        return max_pen
    return (value - low) / (high - low) * max_pen


def round_half_up(value: float) -> int:
    # round(…, 9) first removes binary-float noise such as 38.749999999 → 38.75
    return int(Decimal(str(round(value, 9))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _nutrient_layer(
    n: NutritionInput, is_beverage: bool
) -> tuple[float, list[Penalty], list[Positive]]:
    rules = t.DRINK_THRESHOLDS if is_beverage else t.FOOD_THRESHOLDS
    basis = "100 ml" if is_beverage else "100 g"
    penalties: list[Penalty] = []
    for rule in rules:
        value = getattr(n, rule.field)
        if value is None:
            continue
        pts = interpolate(value, rule.low, rule.high, rule.max_penalty)
        if pts <= 0:
            continue
        level = "high" if value > rule.high else "medium"
        bound = (
            f"> {_fmt(rule.high)} {rule.unit}"
            if level == "high"
            else f"{_fmt(rule.low)}–{_fmt(rule.high)} {rule.unit}"
        )
        penalties.append(
            Penalty(
                factor=rule.factor,
                label=f"{'High' if level == 'high' else 'Medium'} {rule.name.lower()}",
                layer=Layer.NUTRIENT,
                raw_points=round(pts, 4),
                points=round(pts * t.W_NUTRIENT, 4),
                reason=f"{rule.name} {_fmt(value)} {rule.unit}/{basis} is {level} ({bound})",
            )
        )

    positives: list[Positive] = []
    for bonus in t.BONUSES:
        value = getattr(n, bonus.field)
        if value is None:
            continue
        for minimum, pts in bonus.tiers:
            if value >= minimum:
                positives.append(
                    Positive(
                        factor=bonus.factor,
                        label=f"Good source of {bonus.name.lower()}",
                        layer=Layer.NUTRIENT,
                        raw_points=pts,
                        points=round(pts * t.W_NUTRIENT, 4),
                        reason=f"{bonus.name} {_fmt(value)} g/{basis} (≥ {_fmt(minimum)} g)",
                    )
                )
                break

    score = clamp(
        100.0 - sum(p.raw_points for p in penalties) + sum(p.raw_points for p in positives)
    )
    return score, penalties, positives


def _ingredient_layer(
    ingredients: list[Ingredient],
    additives: AdditiveTable,
    extra_codes: Iterable[str],
    weight: float,
) -> tuple[float, list[Penalty], dict[str, object]]:
    penalties: list[Penalty] = []
    flagged: list[str] = []

    def add(factor: str, label: str, raw: float, reason: str, code: str | None = None) -> None:
        penalties.append(
            Penalty(
                factor=factor,
                label=label,
                layer=Layer.INGREDIENT,
                raw_points=raw,
                points=round(raw * weight, 4),
                reason=reason,
                code=code,
            )
        )

    # --- additives (codes found in ingredient text + codes the extractor listed) ---
    codes: list[str] = []
    for ing in ingredients:
        found = additives.codes_in_text(ing.raw, parent=ing.parent)
        if found:
            flagged.append(ing.raw)
        codes.extend(found)
    for code in extra_codes:
        canonical = normalise_code(code) or code.strip()
        if canonical:
            codes.append(canonical)
    codes = list(dict.fromkeys(codes))

    unrated: list[str] = []
    low_concern: list[str] = []
    has_high = False
    has_moderate = False
    for code in codes:
        ref = additives.get(code)
        if ref is None:
            unrated.append(code)  # edge case 30: no penalty, logged for review
            continue
        if ref.risk_tier == "low":
            low_concern.append(code)
            continue
        has_high |= ref.risk_tier == "high"
        has_moderate |= ref.risk_tier == "moderate"
        label_code = "" if code.startswith("X-") else f"{code} "
        add(
            factor=f"additive:{code}",
            label=ref.name.capitalize(),
            raw=t.ADDITIVE_PENALTY[ref.risk_tier],
            reason=_sentence(f"{label_code}{ref.name} — {ref.risk_tier}-concern additive"),
            code=code,
        )
    if low_concern:
        names = ", ".join(low_concern)
        add(
            factor="low_concern_additives",
            label="Low-concern additives",
            raw=t.ADDITIVE_PENALTY["low"] * len(low_concern),
            reason=f"{len(low_concern)} low-concern additive(s): {names}",
        )

    # --- ingredient rules ---
    pho = [i for i in ingredients if is_pho(i)]
    if pho:
        flagged.extend(i.raw for i in pho)
        add(
            "pho",
            "Partially hydrogenated oil",
            t.PENALTY_PHO,
            f"Contains {pho[0].name} — a source of industrial trans fat",
        )
    palm = [i for i in ingredients if is_palm(i)]
    if palm:
        flagged.extend(i.raw for i in palm)
        add("palm_oil", "Palm oil", t.PENALTY_PALM_OIL, "Contains palm oil — high in saturated fat")
    sugar_top3 = [i for i in ingredients if i.position < 3 and is_added_sugar(i)]
    if sugar_top3:
        flagged.extend(i.raw for i in sugar_top3)
        add(
            "added_sugar_top3",
            "Added sugar near the top",
            t.PENALTY_ADDED_SUGAR_TOP3,
            f"{sugar_top3[0].name.capitalize()} is one of the first three ingredients",
        )
    flour_first = [i for i in ingredients if i.position == 0 and is_refined_flour(i)]
    if flour_first:
        flagged.extend(i.raw for i in flour_first)
        add(
            "refined_flour_first",
            "Refined flour first",
            t.PENALTY_REFINED_FLOUR_FIRST,
            "Refined flour (maida) is the main ingredient",
        )

    score = clamp(100.0 - sum(p.raw_points for p in penalties))
    meta: dict[str, object] = {
        "flagged": list(dict.fromkeys(flagged)),
        "unrated": unrated,
        "has_high": has_high,
        "has_pho": bool(pho),
        "additive_count": len(codes),
        "has_concern": has_high or has_moderate,
    }
    return score, penalties, meta


def _verdict(band: Band, penalties: list[Penalty], is_partial: bool) -> str:
    top = [p.label.lower() for p in penalties[:2]]
    lead = {
        Band.VERY_BAD: "Best avoided",
        Band.BAD: "Eat rarely",
        Band.GOOD: "Okay in moderation",
        Band.VERY_GOOD: "A good choice",
        Band.EXCELLENT: "An excellent choice",
    }[band]
    text = f"{lead} — mainly {' and '.join(top)}" if top and band != Band.EXCELLENT else lead
    return f"{text} (partial score)" if is_partial else text


def score(
    nutrition: NutritionInput | None,
    ingredients: list[Ingredient],
    additives: AdditiveTable,
    *,
    is_beverage: bool = False,
    nova: int | None = None,
    extra_additive_codes: Iterable[str] = (),
) -> ScoreResult:
    """Score one product. See module docstring and docs/methodology.md."""
    has_table = nutrition is not None and nutrition.core_present() > 0
    is_partial = not has_table or (
        nutrition is not None and nutrition.core_present() < len(NutritionInput.CORE_FIELDS)
    )

    if has_table:
        assert nutrition is not None
        nutrient_score: float | None
        nutrient_score, n_pen, positives = _nutrient_layer(nutrition, is_beverage)
        w_ing, w_proc = t.W_INGREDIENT, t.W_PROCESSING
    else:
        nutrient_score, n_pen, positives = None, [], []
        w_ing, w_proc = t.W_INGREDIENT_PARTIAL, t.W_PROCESSING_PARTIAL

    ingredient_score, i_pen, meta = _ingredient_layer(
        ingredients, additives, extra_additive_codes, w_ing
    )

    nova_group = (
        nova
        if nova in t.NOVA_SCORE
        else classify_nova(
            ingredients,
            additive_count=int(meta["additive_count"]),  # type: ignore[call-overload]
            has_concern=bool(meta["has_concern"]),
        )
    )
    processing_score = t.NOVA_SCORE[nova_group]
    p_pen: list[Penalty] = []
    if processing_score < 100:
        lost = 100.0 - processing_score
        p_pen.append(
            Penalty(
                factor="processing",
                label="Ultra-processed" if nova_group == 4 else f"Processed (NOVA {nova_group})",
                layer=Layer.PROCESSING,
                raw_points=lost,
                points=round(lost * w_proc, 4),
                reason=f"NOVA group {nova_group} — "
                + {
                    2: "processed culinary ingredient",
                    3: "processed food",
                    4: "ultra-processed food with industrial ingredients or additives",
                }[nova_group],
            )
        )
    elif ingredients:
        positives.append(
            Positive(
                factor="minimally_processed",
                label="Minimally processed",
                layer=Layer.PROCESSING,
                raw_points=0.0,
                points=0.0,
                reason="NOVA group 1 — whole or minimally processed ingredients",
            )
        )
    if ingredients and not meta["additive_count"]:
        positives.append(
            Positive(
                factor="no_additives",
                label="No additives detected",
                layer=Layer.INGREDIENT,
                raw_points=0.0,
                points=0.0,
                reason="No additives were found in the ingredient list",
            )
        )

    if nutrient_score is not None:
        weighted = (
            t.W_NUTRIENT * nutrient_score
            + t.W_INGREDIENT * ingredient_score
            + t.W_PROCESSING * processing_score
        )
    else:
        weighted = w_ing * ingredient_score + w_proc * processing_score

    caps = caps_for(
        nutrition,
        has_pho=bool(meta["has_pho"]),
        has_high_concern_additive=bool(meta["has_high"]),
        is_partial=is_partial,
    )
    final = apply_caps(round_half_up(weighted), caps)
    band = t.band_for(final)

    penalties = sorted(n_pen + i_pen + p_pen, key=lambda p: (-p.points, p.factor))
    positives.sort(key=lambda p: (-p.points, p.factor))
    return ScoreResult(
        score=final,
        band=band,
        verdict=_verdict(band, penalties, is_partial),
        is_partial=is_partial,
        nutrient_score=round(nutrient_score, 4) if nutrient_score is not None else None,
        ingredient_score=round(ingredient_score, 4),
        processing_score=processing_score,
        nova=nova_group,
        penalties=penalties,
        positives=positives,
        caps_applied=caps,
        flagged_ingredients=list(meta["flagged"]),  # type: ignore[call-overload]
        unrated_additives=list(meta["unrated"]),  # type: ignore[call-overload]
        scoring_version=t.SCORING_VERSION,
    )
