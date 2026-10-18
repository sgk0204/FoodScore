"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, TimestampMixin, UTCDateTime, utcnow


class ScanStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DONE = "DONE"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


TERMINAL_STATUSES = frozenset({ScanStatus.DONE, ScanStatus.FAILED, ScanStatus.EXPIRED})


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    # Non-native enum (VARCHAR + CHECK) keeps migrations simple and works on SQLite.
    return Enum(cls, name=name, native_enum=False, length=20, validate_strings=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    diet_profile: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    scans: Mapped[list[Scan]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class RefreshToken(Base):
    """Rotating refresh tokens. A whole ``family`` is revoked when reuse is detected."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    barcode: Mapped[str | None] = mapped_column(String(32), unique=True)
    # Fallback identity when there is no barcode: hash of normalised brand + name (edge 32).
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    is_beverage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latest_scan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    scans: Mapped[list[Scan]] = relationship(back_populates="product")


class Scan(TimestampMixin, Base):
    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    guest_id: Mapped[str | None] = mapped_column(String(64), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        _enum(ScanStatus, "scan_status"), default=ScanStatus.QUEUED, nullable=False, index=True
    )
    score: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_beverage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    barcode: Mapped[str | None] = mapped_column(String(32))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    scoring_version: Mapped[str | None] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(80))
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer)
    llm_cost_usd: Mapped[float | None] = mapped_column(Float)
    image_keys: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # raw LLM output
    ingredients: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    review_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    field_confidence: Mapped[dict[str, float]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # full ScoreResult
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # problem details on FAILED
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User | None] = relationship(back_populates="scans")
    product: Mapped[Product | None] = relationship(back_populates="scans")
    nutrition_facts: Mapped[list[NutritionFacts]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", passive_deletes=True
    )
    penalties: Mapped[list[ScorePenalty]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScorePenalty.position",
    )


class NutritionFacts(Base):
    """Normalised values per 100 g/ml. One row per source: ``llm`` and (after edits) ``user``."""

    __tablename__ = "nutrition_facts"
    __table_args__ = (UniqueConstraint("scan_id", "source", name="uq_nutrition_facts_scan_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # llm | user
    basis: Mapped[str] = mapped_column(String(20), nullable=False)  # per_100g | per_100ml
    energy_kcal: Mapped[float | None] = mapped_column(Float)
    sugar_g: Mapped[float | None] = mapped_column(Float)
    added_sugar_g: Mapped[float | None] = mapped_column(Float)
    carbs_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    sat_fat_g: Mapped[float | None] = mapped_column(Float)
    trans_fat_g: Mapped[float | None] = mapped_column(Float)
    salt_g: Mapped[float | None] = mapped_column(Float)
    fibre_g: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="nutrition_facts")


class ScorePenalty(Base):
    __tablename__ = "score_penalties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # penalty | positive
    factor: Mapped[str] = mapped_column(String(80), nullable=False)
    points_lost: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="penalties")


class AdditiveRefRow(Base):
    """Admin-editable copy of data/additives_ref.csv (seeded by ``python -m app.db.seed``)."""

    __tablename__ = "additives_ref"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(10), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    field: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


__all__ = [
    "TERMINAL_STATUSES",
    "AdditiveRefRow",
    "Feedback",
    "NutritionFacts",
    "Product",
    "RefreshToken",
    "Scan",
    "ScanStatus",
    "ScorePenalty",
    "User",
]
