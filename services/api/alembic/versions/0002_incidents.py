"""add incidents table

Revision ID: 0002_incidents
Revises: 0001_baseline
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_incidents"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default=sa.text("'MEDIUM'")),
        sa.Column("category", sa.String(length=32), nullable=False, server_default=sa.text("'OTHER'")),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'TENANT'")),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.String(length=5000), nullable=False),
        sa.Column("resolution_note", sa.String(length=4000), nullable=True),
        sa.Column("evidence_object_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_tenant_status_created", "incidents", ["tenant_id", "status", "created_at"], unique=False)
    op.create_index("ix_incidents_status_severity_created", "incidents", ["status", "severity", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_incidents_status_severity_created", table_name="incidents")
    op.drop_index("ix_incidents_tenant_status_created", table_name="incidents")
    op.drop_table("incidents")
