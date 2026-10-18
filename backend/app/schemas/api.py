"""Public API contracts (guide §8.2–8.3). The frontend's types are generated from these."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

DISCLAIMER = "For general information only. Not medical or dietary advice."


# --- auth ------------------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
    is_admin: bool


# --- scans -----------------------------------------------------------------------------


class ProductOut(BaseModel):
    name: str | None = None
    brand: str | None = None
    barcode: str | None = None
    category: str | None = None


class FactorOut(BaseModel):
    factor: str
    label: str
    points: float
    reason: str
    code: str | None = None


class CapOut(BaseModel):
    rule: str
    cap: int
    reason: str


class NutritionOut(BaseModel):
    basis: str
    source: Literal["llm", "user"]
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


class ReviewIssueOut(BaseModel):
    field: str
    code: str
    message: str


ScanStatusLiteral = Literal["QUEUED", "PROCESSING", "NEEDS_REVIEW", "DONE", "FAILED", "EXPIRED"]
BandLiteral = Literal["VERY_BAD", "BAD", "GOOD", "VERY_GOOD", "EXCELLENT"]


class ScanOut(BaseModel):
    id: uuid.UUID
    status: ScanStatusLiteral
    score: int | None = None
    band: BandLiteral | None = None
    verdict: str | None = None
    confidence: float | None = None
    is_partial: bool = False
    is_beverage: bool = False
    user_corrected: bool = False
    from_cache: bool = False
    nova: int | None = None
    product: ProductOut = Field(default_factory=ProductOut)
    penalties: list[FactorOut] = Field(default_factory=list)
    positives: list[FactorOut] = Field(default_factory=list)
    caps_applied: list[CapOut] = Field(default_factory=list)
    nutrition: NutritionOut | None = None
    ingredients: list[str] = Field(default_factory=list)
    flagged_ingredients: list[str] = Field(default_factory=list)
    unrated_additives: list[str] = Field(default_factory=list)
    review_issues: list[ReviewIssueOut] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    prompt_version: str | None = None
    scoring_version: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    disclaimer: str = DISCLAIMER


class ScanSummaryOut(BaseModel):
    id: uuid.UUID
    status: ScanStatusLiteral
    score: int | None
    band: BandLiteral | None
    product: ProductOut
    is_partial: bool
    user_corrected: bool
    created_at: datetime


class ScanPage(BaseModel):
    items: list[ScanSummaryOut]
    next_cursor: str | None


class NutritionPatch(BaseModel):
    """User corrections, always per 100 g (or 100 ml for drinks). Omitted fields are kept."""

    model_config = ConfigDict(extra="forbid")

    energy_kcal: float | None = Field(default=None, ge=0, le=900)
    sugars_g: float | None = Field(default=None, ge=0, le=100)
    added_sugars_g: float | None = Field(default=None, ge=0, le=100)
    carbs_g: float | None = Field(default=None, ge=0, le=100)
    fat_g: float | None = Field(default=None, ge=0, le=100)
    sat_fat_g: float | None = Field(default=None, ge=0, le=100)
    trans_fat_g: float | None = Field(default=None, ge=0, le=100)
    salt_g: float | None = Field(default=None, ge=0, le=50)
    fibre_g: float | None = Field(default=None, ge=0, le=100)
    protein_g: float | None = Field(default=None, ge=0, le=100)
    ingredients: list[str] | None = Field(default=None, max_length=200)
    is_beverage: bool | None = None


class FeedbackIn(BaseModel):
    type: Literal["wrong_value", "unfair_score", "wrong_product", "other"]
    field: str | None = Field(default=None, max_length=50)
    comment: str = Field(default="", max_length=2000)


class FeedbackOut(BaseModel):
    id: int
    status: Literal["received"] = "received"


class PublicProductOut(BaseModel):
    barcode: str
    product: ProductOut
    score: int | None
    band: BandLiteral | None
    verdict: str | None
    is_partial: bool
    penalties: list[FactorOut]
    positives: list[FactorOut]
    scored_at: str | None
    verified: bool
