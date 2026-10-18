"""Unit parsing, normalisation and sanity checks (guide §7.4, edge cases 11–19)."""

from __future__ import annotations

import pytest

from app.schemas.extraction import Extraction, LegibilityIssue, NutrientValue
from app.services.normalise import sanity
from app.services.normalise.normaliser import normalise
from app.services.normalise.units import parse_amount
from app.services.scoring import NutritionInput


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<0.5 g", (0.25, "g")),
        ("less than 1 g", (0.5, "g")),
        ("Nil", (0.0, None)),
        ("traces", (0.0, None)),
        ("-", (0.0, None)),
        ("–", (0.0, None)),
        ("5,2 g", (5.2, "g")),
        ("480 kcal", (480.0, "kcal")),
        ("2008 kJ / 480 kcal", (480.0, "kcal")),
        ("2008kJ", (2008.0, "kJ")),
        ("240 mg", (240.0, "mg")),
        ("12", (12.0, None)),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def nv(raw: str | None = None, value: float | None = None, unit=None, confidence: float = 0.95):
    return NutrientValue(raw=raw, value=value, unit=unit, confidence=confidence)


def make_extraction(**overrides) -> Extraction:
    base = {
        "is_food_label": True,
        "image_roles": ["front", "nutrition", "ingredients"],
        "product_name": "Choco Cream",
        "brand": "Acme",
        "category_guess": "snack",
        "basis": "per_100g",
        "energy": nv("480 kcal"),
        "sugars": nv("30 g"),
        "carbohydrates": nv("62 g"),
        "total_fat": nv("22 g"),
        "saturated_fat": nv("10 g"),
        "sodium_or_salt": nv("0.6 g"),
        "salt_label": "salt",
        "fibre": nv("2 g"),
        "protein": nv("6 g"),
    }
    base.update(overrides)
    return Extraction(**base)


def test_clean_label_passes_without_review():
    out = normalise(make_extraction())
    assert out.nutrition is not None
    assert out.nutrition.energy_kcal == 480
    assert out.nutrition.salt_g == 0.6
    assert not out.needs_review, out.issues
    assert out.confidence == pytest.approx(0.95)


def test_kj_converted_to_kcal():
    out = normalise(make_extraction(energy=nv("2008 kJ")))
    assert out.nutrition.energy_kcal == pytest.approx(479.92, abs=0.01)


def test_sodium_mg_converted_to_salt():
    out = normalise(make_extraction(sodium_or_salt=nv("240 mg"), salt_label="sodium"))
    assert out.nutrition.salt_g == pytest.approx(0.6)


def test_sodium_mg_without_label_is_treated_as_sodium():
    out = normalise(make_extraction(sodium_or_salt=nv("240 mg"), salt_label=None))
    assert out.nutrition.salt_g == pytest.approx(0.6)


def test_value_used_when_raw_missing():
    out = normalise(make_extraction(sugars=nv(None, 30, "g")))
    assert out.nutrition.sugars_g == 30


def test_per_serving_converted_with_serving_size():
    # edge case 11: 30 g serving with 9 g sugar → 30 g / 100 g
    out = normalise(
        make_extraction(basis="per_serving", serving_size_g=30, sugars=nv("9 g"), energy=nv("144"))
    )
    assert out.basis == "per_100g"
    assert out.nutrition.sugars_g == pytest.approx(30)
    assert out.nutrition.energy_kcal == pytest.approx(480)


def test_per_serving_without_serving_size_needs_review():
    out = normalise(make_extraction(basis="per_serving", serving_size_g=None))
    assert out.needs_review
    assert any(i.code == "serving_size_missing" for i in out.issues)


def test_beverage_detected_from_basis():
    out = normalise(make_extraction(basis="per_100ml", category_guess="other"))
    assert out.is_beverage


def test_decimal_misread_is_flagged():
    # edge case 16: saturated fat read as 52 instead of 5.2
    out = normalise(make_extraction(saturated_fat=nv("52 g")))
    assert out.needs_review
    codes = {i.code for i in out.issues}
    assert "subtotal" in codes


def test_low_confidence_field_needs_review():
    out = normalise(make_extraction(sugars=nv("30 g", confidence=0.4)))
    assert out.needs_review
    assert any(i.field == "sugars_g" and i.code == "low_confidence" for i in out.issues)


def test_empty_table_with_glare_is_unreadable():
    ex = make_extraction(
        energy=nv(None, confidence=0),
        sugars=nv(None, confidence=0),
        carbohydrates=nv(None, confidence=0),
        total_fat=nv(None, confidence=0),
        saturated_fat=nv(None, confidence=0),
        sodium_or_salt=nv(None, confidence=0),
        fibre=nv(None, confidence=0),
        protein=nv(None, confidence=0),
        legibility_issues=[LegibilityIssue(image="nutrition", issue="strong glare")],
    )
    out = normalise(ex)
    assert out.nutrition is None
    assert out.nutrition_unreadable


def test_no_table_without_legibility_issue_is_partial_not_unreadable():
    ex = make_extraction(
        **{
            f: nv(None, confidence=0)
            for f in (
                "energy",
                "sugars",
                "carbohydrates",
                "total_fat",
                "saturated_fat",
                "sodium_or_salt",
                "fibre",
                "protein",
            )
        }
    )
    out = normalise(ex)
    assert out.nutrition is None
    assert not out.nutrition_unreadable
    assert not out.needs_review


# --- sanity checks -----------------------------------------------------------------


def codes(n: NutritionInput) -> set[str]:
    return {i.code for i in sanity.check(n)}


def test_sanity_macro_sum():
    assert "macro_sum" in codes(NutritionInput(fat_g=50, carbs_g=50, protein_g=10))


def test_sanity_sugar_above_carbs():
    assert "subtotal" in codes(NutritionInput(sugars_g=40, carbs_g=30))


def test_sanity_added_above_total_sugar():
    assert "subtotal" in codes(NutritionInput(sugars_g=10, added_sugars_g=20))


def test_sanity_energy_mismatch():
    n = NutritionInput(energy_kcal=100, protein_g=6, carbs_g=62, fat_g=22)
    assert "energy_mismatch" in codes(n)


def test_sanity_energy_within_tolerance():
    n = NutritionInput(energy_kcal=480, protein_g=6, carbs_g=62, fat_g=22, fibre_g=2)
    assert "energy_mismatch" not in codes(n)


def test_sanity_ranges():
    assert "out_of_range" in codes(NutritionInput(salt_g=60))
    assert "out_of_range" in codes(NutritionInput(energy_kcal=950))
    assert codes(NutritionInput(salt_g=1, energy_kcal=500)) == set()
