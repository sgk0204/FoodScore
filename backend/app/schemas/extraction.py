"""Structured output the vision LLM must return (guide §7.2).

Deviations from the guide sketch, all deliberate:
- ``raw`` on every NutrientValue: the model transcribes the printed text ("<0.5 g", "Nil",
  "5,2") and *code* parses it, so label quirks are handled deterministically (edge case 15).
- ``carbohydrates`` added: needed by the macro-sum, sub-total and energy cross-checks.
- ``image_roles`` is a list aligned with the uploaded images instead of a dict, which maps
  cleanly onto every provider's JSON-schema support.
- ``legibility_issues`` names the photo, so the UI can ask for a *specific* retake.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImageRole = Literal["front", "nutrition", "ingredients", "other"]
Unit = Literal["g", "mg", "mcg", "kcal", "kJ", "ml"]
Category = Literal["snack", "beverage", "dairy", "cereal", "sauce", "other"]
Basis = Literal["per_100g", "per_100ml", "per_serving", "unknown"]

NUTRIENT_FIELDS: tuple[str, ...] = (
    "energy",
    "sugars",
    "added_sugars",
    "carbohydrates",
    "total_fat",
    "saturated_fat",
    "trans_fat",
    "sodium_or_salt",
    "fibre",
    "protein",
)


class NutrientValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str | None = Field(
        default=None, description="Exact text printed in the per-100 g/ml column, e.g. '<0.5 g'"
    )
    value: float | None = Field(
        default=None, description="Numeric value as printed; null if not printed - never guessed"
    )
    unit: Unit | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)


class LegibilityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: ImageRole
    issue: str = Field(description="Short description, e.g. 'strong glare over the table'")


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_food_label: bool
    image_roles: list[ImageRole] = Field(description="Role of each image, in upload order")
    product_name: str | None = None
    brand: str | None = None
    category_guess: Category = "other"
    basis: Basis = "unknown"
    serving_size_g: float | None = None
    energy: NutrientValue = Field(default_factory=NutrientValue)
    sugars: NutrientValue = Field(default_factory=NutrientValue)
    added_sugars: NutrientValue = Field(default_factory=NutrientValue)
    carbohydrates: NutrientValue = Field(default_factory=NutrientValue)
    total_fat: NutrientValue = Field(default_factory=NutrientValue)
    saturated_fat: NutrientValue = Field(default_factory=NutrientValue)
    trans_fat: NutrientValue = Field(default_factory=NutrientValue)
    sodium_or_salt: NutrientValue = Field(default_factory=NutrientValue)
    salt_label: Literal["sodium", "salt"] | None = None
    fibre: NutrientValue = Field(default_factory=NutrientValue)
    protein: NutrientValue = Field(default_factory=NutrientValue)
    ingredients: list[str] = Field(
        default_factory=list,
        description="Label order; sub-ingredients as 'Parent > child'; English names",
    )
    additive_codes: list[str] = Field(default_factory=list, description="e.g. 'INS 211'")
    legibility_issues: list[LegibilityIssue] = Field(default_factory=list)
    multiple_products: bool = False
