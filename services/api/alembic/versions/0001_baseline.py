"""baseline mydata core tables

Revision ID: 0001_baseline
Revises:
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "licenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("license_type", sa.String(length=64), nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_licenses_tenant_status", "licenses", ["tenant_id", "status"], unique=False)
    op.create_index("ix_licenses_tenant_type", "licenses", ["tenant_id", "license_type"], unique=False)

    op.create_table(
        "guard_heartbeats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "device_id", name="uq_guard_heartbeat_tenant_device"),
    )
    op.create_index("ix_guard_heartbeat_tenant", "guard_heartbeats", ["tenant_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("target", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_tenant_ts", "audit_log", ["tenant_id", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_guard_heartbeat_tenant", table_name="guard_heartbeats")
    op.drop_table("guard_heartbeats")
    op.drop_index("ix_licenses_tenant_type", table_name="licenses")
    op.drop_index("ix_licenses_tenant_status", table_name="licenses")
    op.drop_table("licenses")
    op.drop_table("tenants")
