"""add storage grants table

Revision ID: 0003_storage_grants
Revises: 0002_incidents
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_storage_grants"
down_revision = "0002_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ISSUED'")),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_grants_tenant_status_exp", "storage_grants", ["tenant_id", "status", "expires_at"], unique=False)
    op.create_index("ix_storage_grants_status_exp", "storage_grants", ["status", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_storage_grants_status_exp", table_name="storage_grants")
    op.drop_index("ix_storage_grants_tenant_status_exp", table_name="storage_grants")
    op.drop_table("storage_grants")