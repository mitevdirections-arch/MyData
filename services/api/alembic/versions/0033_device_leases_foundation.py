"""add missing device_leases table

Revision ID: 0033_device_leases_foundation
Revises: 0032_partners_v1_foundation
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0033_device_leases_foundation"
down_revision = "0032_partners_v1_foundation"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(idx.get("name") == index_name for idx in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "device_leases"):
        op.create_table(
            "device_leases",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("device_id", sa.String(length=128), nullable=False),
            sa.Column("device_class", sa.String(length=32), nullable=False, server_default=sa.text("'desktop'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("leased_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_device_lease_tenant_user"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "device_leases") and not _has_index(insp, "device_leases", "ix_device_lease_tenant_user"):
        op.create_index("ix_device_lease_tenant_user", "device_leases", ["tenant_id", "user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _has_table(insp, "device_leases"):
        if _has_index(insp, "device_leases", "ix_device_lease_tenant_user"):
            op.drop_index("ix_device_lease_tenant_user", table_name="device_leases")
        op.drop_table("device_leases")
