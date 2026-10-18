"""Scoring engine tests. Each edge case in guide §9.3 maps to at least one test here."""

from __future__ import annotations

import pytest

from app.services.scoring import Band, NutritionInput, band_for, parse_ingredients, score
from app.services.scoring.engine import interpolate, round_half_up
from app.services.scoring.thresholds import DRINK_THRESHOLDS, FOOD_THRESHOLDS

BISCUIT = NutritionInput(
    energy_kcal=480,
    sugars_g=30,
    fat_g=22,
    sat_fat_g=10,
    salt_g=0.6,
    fibre_g=2,
    protein_g=6,
)
BISCUIT_INGREDIENTS = [
    "Whole wheat flour",
    "Palm oil",
    "Cocoa solids",
    "Sugar",
    "Emulsifier (INS 322)",
    "Raising agent (INS 503)",
    "Artificial flavour (chocolate)",
]


# --- §6.6 worked example --------------------------------------------------------------


def test_worked_example_chocolate_cream_biscuit(additives):
    result = score(BISCUIT, parse_ingredients(BISCUIT_INGREDIENTS), additives, nova=4)

    assert result.nutrient_score == pytest.approx(28.75)
    assert result.ingredient_score == pytest.approx(65)
    assert result.processing_score == 20
    assert result.score == 39
    assert result.band is Band.BAD
    assert not result.is_partial
    assert result.caps_applied == []


def test_worked_example_reasons_ranked_by_weighted_points(additives):
    result = score(BISCUIT, parse_ingredients(BISCUIT_INGREDIENTS), additives, nova=4)
    got = [(p.factor, round(p.points, 2)) for p in result.penalties]
    assert got == [
        ("sugar", 18.0),
        ("sat_fat", 15.0),
        ("processing", 8.0),
        ("fat", 6.0),
        ("additive:X-ARTIFICIAL-FLAVOUR", 4.5),
        ("salt", 3.75),
        ("low_concern_additives", 3.0),
        ("palm_oil", 3.0),
        ("energy", 2.4),
    ]
    assert [(p.factor, p.points) for p in result.positives] == [("protein", 2.4)]


def test_worked_example_nova_is_inferred_as_4(additives):
    result = score(BISCUIT, parse_ingredients(BISCUIT_INGREDIENTS), additives)
    assert result.nova == 4
    assert result.score == 39


def test_reason_text_is_plain_language(additives):
    result = score(BISCUIT, parse_ingredients(BISCUIT_INGREDIENTS), additives)
    sugar = next(p for p in result.penalties if p.factor == "sugar")
    assert sugar.reason == "Sugar 30 g/100 g is high (> 22.5 g)"
    salt = next(p for p in result.penalties if p.factor == "salt")
    assert salt.reason == "Salt 0.6 g/100 g is medium (0.3–1.5 g)"


def test_score_is_reproducible(additives):
    ings = parse_ingredients(BISCUIT_INGREDIENTS)
    results = {score(BISCUIT, ings, additives).model_dump_json() for _ in range(20)}
    assert len(results) == 1


# --- interpolation & thresholds (edge case 28) ----------------------------------------


@pytest.mark.parametrize("rule", FOOD_THRESHOLDS + DRINK_THRESHOLDS, ids=lambda r: r.factor)
def test_threshold_boundaries(rule):
    # low is inclusive (costs nothing), high is exclusive (exactly high is not yet max)
    assert interpolate(rule.low, rule.low, rule.high, rule.max_penalty) == 0
    assert interpolate(rule.high, rule.low, rule.high, rule.max_penalty) == pytest.approx(
        rule.max_penalty
    )
    assert interpolate(rule.high + 0.001, rule.low, rule.high, rule.max_penalty) == rule.max_penalty
    mid = (rule.low + rule.high) / 2
    assert interpolate(mid, rule.low, rule.high, rule.max_penalty) == pytest.approx(
        rule.max_penalty / 2
    )


def test_value_just_above_low_costs_a_little():
    assert 0 < interpolate(5.01, 5, 22.5, 30) < 0.1


# --- rounding & bands (edge case 29) --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(60.5, 61), (60.49, 60), (38.75, 39), (20.5, 21), (0.5, 1), (99.5, 100), (40.0, 40)],
)
def test_round_half_up(value, expected):
    assert round_half_up(value) == expected


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0, Band.VERY_BAD),
        (20, Band.VERY_BAD),
        (21, Band.BAD),
        (40, Band.BAD),
        (41, Band.GOOD),
        (60, Band.GOOD),
        (61, Band.VERY_GOOD),
        (80, Band.VERY_GOOD),
        (81, Band.EXCELLENT),
        (100, Band.EXCELLENT),
    ],
)
def test_band_boundaries(value, band):
    assert band_for(value) is band


def test_rounding_happens_before_banding():
    # 60.5 must become 61 → Very Good, not 60 → Good
    assert band_for(round_half_up(60.5)) is Band.VERY_GOOD


# --- bonuses ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fibre", "protein", "bonus"),
    [(2.9, 4.9, 0), (3, 0, 5), (6, 0, 10), (0, 5, 4), (0, 10, 8), (6, 10, 18)],
)
def test_bonus_tiers(additives, fibre, protein, bonus):
    n = NutritionInput(
        energy_kcal=500,
        sugars_g=30,
        fat_g=20,
        sat_fat_g=10,
        salt_g=2,
        fibre_g=fibre,
        protein_g=protein,
    )
    result = score(n, [], additives)
    base = 100 - 30 - 25 - 25 - 10 - 5  # energy 500 → 5 points
    assert result.nutrient_score == pytest.approx(base + bonus)


def test_nutrient_score_is_clamped(additives):
    terrible = NutritionInput(
        energy_kcal=900, sugars_g=90, fat_g=90, sat_fat_g=50, salt_g=10, fibre_g=0, protein_g=0
    )
    assert score(terrible, [], additives).nutrient_score == 0


# --- caps (§6.4) -----------------------------------------------------------------------

HEALTHY = NutritionInput(
    energy_kcal=350, sugars_g=2, fat_g=2, sat_fat_g=0.5, salt_g=0.1, fibre_g=8, protein_g=12
)


def test_healthy_single_ingredient_food_is_excellent(additives):
    # edge case 27: single whole food → NOVA 1, no additive penalties
    result = score(HEALTHY, parse_ingredients(["Rolled oats"]), additives)
    assert result.nova == 1
    assert result.score == 100
    assert result.band is Band.EXCELLENT
    assert {p.factor for p in result.positives} >= {"fibre", "protein", "minimally_processed"}


def test_trans_fat_cap(additives):
    n = HEALTHY.model_copy(update={"trans_fat_g": 0.3})
    result = score(n, parse_ingredients(["Rolled oats"]), additives)
    assert result.score == 40
    assert [c.rule for c in result.caps_applied] == ["trans_fat"]


def test_trans_fat_at_limit_is_not_capped(additives):
    n = HEALTHY.model_copy(update={"trans_fat_g": 0.2})
    assert score(n, parse_ingredients(["Rolled oats"]), additives).score > 40


def test_pho_ingredient_caps_and_penalises(additives):
    result = score(HEALTHY, parse_ingredients(["Oats", "Vanaspati"]), additives)
    assert result.score <= 40
    assert any(p.factor == "pho" and p.raw_points == 30 for p in result.penalties)


def test_high_concern_additive_cap(additives):
    result = score(HEALTHY, parse_ingredients(["Oats", "Colour (INS 171)"]), additives)
    assert result.score <= 50
    assert any(c.rule == "high_concern_additive" for c in result.caps_applied)
    assert any(p.factor == "additive:INS 171" and p.raw_points == 30 for p in result.penalties)


def test_multiple_caps_lowest_wins(additives):
    n = HEALTHY.model_copy(update={"trans_fat_g": 1})
    result = score(n, parse_ingredients(["Oats", "titanium dioxide"]), additives)
    assert result.score <= 40
    assert {c.rule for c in result.caps_applied} == {"trans_fat", "high_concern_additive"}


# --- partial scores (edge cases 5, 19) -------------------------------------------------


def test_no_nutrition_table_scores_ingredients_and_processing_only(additives):
    result = score(None, parse_ingredients(["Rolled oats"]), additives)
    assert result.is_partial
    assert result.nutrient_score is None
    assert result.score == 60  # 100 from ingredients/processing, capped at 60
    assert result.band is Band.GOOD
    assert "partial" in result.verdict


def test_incomplete_nutrition_table_is_partial(additives):
    n = NutritionInput(energy_kcal=350, sugars_g=2)
    result = score(n, parse_ingredients(["Rolled oats"]), additives)
    assert result.is_partial
    assert result.score <= 60


# --- beverages (edge cases 17, 26) -----------------------------------------------------


def test_drinks_use_drink_thresholds(additives):
    cola = NutritionInput(energy_kcal=42, sugars_g=10.6, fat_g=0, sat_fat_g=0, salt_g=0.01)
    food = score(cola, [], additives, is_beverage=False)
    drink = score(cola, [], additives, is_beverage=True)
    assert drink.nutrient_score < food.nutrient_score
    assert next(p for p in drink.penalties if p.factor == "sugar").reason.endswith("(2.5–11.25 g)")


def test_zero_sugar_drink_still_penalised_for_sweeteners_and_processing(additives):
    diet = NutritionInput(energy_kcal=1, sugars_g=0, fat_g=0, sat_fat_g=0, salt_g=0.02)
    ings = parse_ingredients(
        ["Carbonated water", "Colour (150d)", "Acidity regulator (338)", "Sweeteners (951, 950)"]
    )
    result = score(diet, ings, additives, is_beverage=True)
    assert result.nutrient_score == 100
    assert result.nova == 4
    codes = {p.code for p in result.penalties if p.code}
    assert {"INS 951", "INS 950", "INS 150d"} <= codes
    assert "INS 338" in result.unrated_additives
    assert result.score < 90


# --- ingredient rules ------------------------------------------------------------------


def test_added_sugar_in_first_three(additives):
    result = score(HEALTHY, parse_ingredients(["Sugar", "Wheat flour", "Cocoa"]), additives)
    assert any(p.factor == "added_sugar_top3" for p in result.penalties)
    result = score(HEALTHY, parse_ingredients(["Oats", "Nuts", "Seeds", "Sugar"]), additives)
    assert not any(p.factor == "added_sugar_top3" for p in result.penalties)


def test_no_added_sugar_claim_is_not_sugar(additives):
    result = score(HEALTHY, parse_ingredients(["Oats", "No added sugar"]), additives)
    assert not any(p.factor == "added_sugar_top3" for p in result.penalties)


def test_refined_flour_first(additives):
    result = score(HEALTHY, parse_ingredients(["Refined wheat flour (maida)", "Salt"]), additives)
    assert any(p.factor == "refined_flour_first" for p in result.penalties)
    result = score(HEALTHY, parse_ingredients(["Salt", "Maida"]), additives)
    assert not any(p.factor == "refined_flour_first" for p in result.penalties)


def test_nested_ingredients_count_for_flags(additives):
    # edge case 22: "Filling (sugar, palm oil)"
    ings = parse_ingredients(["Wheat flour", "Cream filling (sugar, palm oil, emulsifier (322))"])
    result = score(HEALTHY, ings, additives)
    factors = {p.factor for p in result.penalties}
    assert {"palm_oil", "added_sugar_top3", "low_concern_additives"} <= factors


def test_palm_oil_penalised_once(additives):
    ings = parse_ingredients(["Palm oil", "Palmolein", "Oats"])
    result = score(HEALTHY, ings, additives)
    assert sum(1 for p in result.penalties if p.factor == "palm_oil") == 1


def test_unknown_additive_is_unrated_not_penalised(additives):
    # edge case 30
    result = score(HEALTHY, parse_ingredients(["Oats", "Stabiliser (INS 9999)"]), additives)
    assert "INS 9999" in result.unrated_additives
    assert not any(p.code == "INS 9999" for p in result.penalties)


def test_extra_additive_codes_from_extractor_are_counted_once(additives):
    ings = parse_ingredients(["Oats", "Preservative (INS 211)"])
    result = score(HEALTHY, ings, additives, extra_additive_codes=["E211", "INS 211"])
    assert sum(1 for p in result.penalties if p.code == "INS 211") == 1


def test_ingredient_score_is_clamped(additives):
    ings = parse_ingredients(["Oats", "Colours (102, 110, 122, 124, 129, 127, 133)"])
    assert score(HEALTHY, ings, additives).ingredient_score == 0


def test_penalties_sorted_descending(additives):
    result = score(BISCUIT, parse_ingredients(BISCUIT_INGREDIENTS), additives)
    points = [p.points for p in result.penalties]
    assert points == sorted(points, reverse=True)


def test_reason_shown_whenever_score_below_81(additives):
    # user story 1: at least one reason when score < 81
    for n, ings in [
        (BISCUIT, BISCUIT_INGREDIENTS),
        (HEALTHY, ["Oats", "Sugar", "Palm oil"]),
        (None, ["Oats"]),
    ]:
        result = score(n, parse_ingredients(ings), additives)
        if result.score < 81:
            assert result.penalties or result.caps_applied
