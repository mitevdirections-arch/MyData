"""add marketplace foundation tables

Revision ID: 0014_marketplace_foundation
Revises: 0013_support_channels
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_marketplace_foundation"
down_revision = "0013_support_channels"
branch_labels = None
depends_on = None


def _has_index(insp, table_name: str, idx: str) -> bool:
    try:
        return any(i.get("name") == idx for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_unique(insp, table_name: str, uq_name: str) -> bool:
    try:
        return any(c.get("name") == uq_name for c in insp.get_unique_constraints(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "marketplace_modules" not in insp.get_table_names():
        op.create_table(
            "marketplace_modules",
            sa.Column("module_code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("module_class", sa.String(length=64), nullable=False, server_default=sa.text("'GENERAL'")),
            sa.Column("description", sa.String(length=4000), nullable=True),
            sa.Column("default_license_type", sa.String(length=32), nullable=False, server_default=sa.text("'MODULE_PAID'")),
            sa.Column("base_price_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default=sa.text("'EUR'")),
            sa.Column("billing_period", sa.String(length=16), nullable=False, server_default=sa.text("'MONTH'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("module_code"),
        )

    if "marketplace_offers" not in insp.get_table_names():
        op.create_table(
            "marketplace_offers",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.String(length=5000), nullable=True),
            sa.Column("module_code", sa.String(length=64), sa.ForeignKey("marketplace_modules.module_code", ondelete="SET NULL"), nullable=True),
            sa.Column("offer_type", sa.String(length=32), nullable=False, server_default=sa.text("'DISCOUNT'")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("discount_percent", sa.Integer(), nullable=True),
            sa.Column("trial_days", sa.Integer(), nullable=True),
            sa.Column("price_override_minor", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=True),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "marketplace_modules" in insp.get_table_names() and not _has_index(insp, "marketplace_modules", "ix_marketplace_modules_active_class"):
        op.create_index("ix_marketplace_modules_active_class", "marketplace_modules", ["is_active", "module_class"], unique=False)

    if "marketplace_offers" in insp.get_table_names() and not _has_unique(insp, "marketplace_offers", "uq_marketplace_offer_code"):
        op.create_unique_constraint("uq_marketplace_offer_code", "marketplace_offers", ["code"])

    if "marketplace_offers" in insp.get_table_names() and not _has_index(insp, "marketplace_offers", "ix_marketplace_offers_status_window"):
        op.create_index("ix_marketplace_offers_status_window", "marketplace_offers", ["status", "starts_at", "ends_at"], unique=False)

    if "marketplace_offers" in insp.get_table_names() and not _has_index(insp, "marketplace_offers", "ix_marketplace_offers_module_status"):
        op.create_index("ix_marketplace_offers_module_status", "marketplace_offers", ["module_code", "status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "marketplace_offers" in insp.get_table_names():
        if _has_index(insp, "marketplace_offers", "ix_marketplace_offers_module_status"):
            op.drop_index("ix_marketplace_offers_module_status", table_name="marketplace_offers")
        if _has_index(insp, "marketplace_offers", "ix_marketplace_offers_status_window"):
            op.drop_index("ix_marketplace_offers_status_window", table_name="marketplace_offers")
        if _has_unique(insp, "marketplace_offers", "uq_marketplace_offer_code"):
            op.drop_constraint("uq_marketplace_offer_code", "marketplace_offers", type_="unique")
        op.drop_table("marketplace_offers")

    insp = sa.inspect(bind)
    if "marketplace_modules" in insp.get_table_names():
        if _has_index(insp, "marketplace_modules", "ix_marketplace_modules_active_class"):
            op.drop_index("ix_marketplace_modules_active_class", table_name="marketplace_modules")
        op.drop_table("marketplace_modules")