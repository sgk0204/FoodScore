"""Initial schema: users, refresh tokens, products, scans, nutrition, penalties, additives, feedback.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
STATUSES = ("QUEUED", "PROCESSING", "NEEDS_REVIEW", "DONE", "FAILED", "EXPIRED")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("diet_profile", JSON, nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("barcode", sa.String(32), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("is_beverage", sa.Boolean(), nullable=False),
        sa.Column("latest_scan_id", sa.Uuid(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("barcode", name="uq_products_barcode"),
        sa.UniqueConstraint("fingerprint", name="uq_products_fingerprint"),
    )

    op.create_table(
        "scans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("guest_id", sa.String(64), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                *STATUSES, name="scan_status", native_enum=False, length=20, create_constraint=False
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("band", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False),
        sa.Column("is_beverage", sa.Boolean(), nullable=False),
        sa.Column("user_corrected", sa.Boolean(), nullable=False),
        sa.Column("from_cache", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("barcode", sa.String(32), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("scoring_version", sa.String(20), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("llm_cost_usd", sa.Float(), nullable=True),
        sa.Column("image_keys", JSON, nullable=False),
        sa.Column("extraction", JSON, nullable=True),
        sa.Column("ingredients", JSON, nullable=False),
        sa.Column("review_issues", JSON, nullable=False),
        sa.Column("field_confidence", JSON, nullable=False),
        sa.Column("result", JSON, nullable=True),
        sa.Column("error", JSON, nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(f"status IN {STATUSES!r}", name="ck_scans_scan_status"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_scans_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_scans_product_id_products",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scans"),
        sa.UniqueConstraint("idempotency_key", name="uq_scans_idempotency_key"),
    )
    op.create_index("ix_scans_user_created", "scans", ["user_id", "created_at"])
    op.create_index("ix_scans_guest_id", "scans", ["guest_id"])
    op.create_index("ix_scans_product_id", "scans", ["product_id"])
    op.create_index("ix_scans_status", "scans", ["status"])

    op.create_table(
        "nutrition_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("energy_kcal", sa.Float(), nullable=True),
        sa.Column("sugar_g", sa.Float(), nullable=True),
        sa.Column("added_sugar_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("sat_fat_g", sa.Float(), nullable=True),
        sa.Column("trans_fat_g", sa.Float(), nullable=True),
        sa.Column("salt_g", sa.Float(), nullable=True),
        sa.Column("fibre_g", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_nutrition_facts_scan_id_scans", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nutrition_facts"),
        sa.UniqueConstraint("scan_id", "source", name="uq_nutrition_facts_scan_source"),
    )
    op.create_index("ix_nutrition_facts_scan_id", "nutrition_facts", ["scan_id"])

    op.create_table(
        "score_penalties",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("factor", sa.String(80), nullable=False),
        sa.Column("points_lost", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_score_penalties_scan_id_scans", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_score_penalties"),
    )
    op.create_index("ix_score_penalties_scan_id", "score_penalties", ["scan_id"])

    op.create_table(
        "additives_ref",
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", JSON, nullable=False),
        sa.Column("risk_tier", sa.String(10), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_additives_ref"),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("field", sa.String(50), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name="fk_feedback_scan_id_scans", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feedback_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
    )
    op.create_index("ix_feedback_scan_id", "feedback", ["scan_id"])

    # Postgres-only: trigram index for history search by product name (guide §8.1).
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute("CREATE INDEX ix_products_name_trgm ON products USING gin (name gin_trgm_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
    for table in (
        "feedback",
        "additives_ref",
        "score_penalties",
        "nutrition_facts",
        "scans",
        "products",
        "refresh_tokens",
        "users",
    ):
        op.drop_table(table)
