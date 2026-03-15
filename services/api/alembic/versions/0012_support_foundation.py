"""add support request and session foundation tables

Revision ID: 0012_support_foundation
Revises: 0011_public_experience
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_support_foundation"
down_revision = "0011_public_experience"
branch_labels = None
depends_on = None


def _has_index(insp, table_name: str, idx: str) -> bool:
    try:
        return any(i.get("name") == idx for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "support_requests" not in insp.get_table_names():
        op.create_table(
            "support_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'NEW'")),
            sa.Column("channel", sa.String(length=32), nullable=False, server_default=sa.text("'LIVE_ACCESS'")),
            sa.Column("priority", sa.String(length=16), nullable=False, server_default=sa.text("'MEDIUM'")),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.String(length=5000), nullable=False),
            sa.Column("requested_by", sa.String(length=255), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("door_opened_by", sa.String(length=255), nullable=True),
            sa.Column("door_opened_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("door_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("session_started_by", sa.String(length=255), nullable=True),
            sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_by", sa.String(length=255), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("close_reason", sa.String(length=1024), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    if "support_sessions" not in insp.get_table_names():
        op.create_table(
            "support_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("started_by", sa.String(length=255), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_by", sa.String(length=255), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_reason", sa.String(length=1024), nullable=True),
            sa.Column("capabilities_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "support_requests" in insp.get_table_names() and not _has_index(insp, "support_requests", "ix_support_requests_tenant_status_created"):
        op.create_index("ix_support_requests_tenant_status_created", "support_requests", ["tenant_id", "status", "requested_at"], unique=False)

    if "support_requests" in insp.get_table_names() and not _has_index(insp, "support_requests", "ix_support_requests_status_door"):
        op.create_index("ix_support_requests_status_door", "support_requests", ["status", "door_expires_at", "requested_at"], unique=False)

    if "support_sessions" in insp.get_table_names() and not _has_index(insp, "support_sessions", "ix_support_sessions_tenant_status_exp"):
        op.create_index("ix_support_sessions_tenant_status_exp", "support_sessions", ["tenant_id", "status", "expires_at"], unique=False)

    if "support_sessions" in insp.get_table_names() and not _has_index(insp, "support_sessions", "ix_support_sessions_request_started"):
        op.create_index("ix_support_sessions_request_started", "support_sessions", ["request_id", "started_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "support_sessions" in insp.get_table_names():
        if _has_index(insp, "support_sessions", "ix_support_sessions_request_started"):
            op.drop_index("ix_support_sessions_request_started", table_name="support_sessions")
        if _has_index(insp, "support_sessions", "ix_support_sessions_tenant_status_exp"):
            op.drop_index("ix_support_sessions_tenant_status_exp", table_name="support_sessions")
        op.drop_table("support_sessions")

    insp = sa.inspect(bind)
    if "support_requests" in insp.get_table_names():
        if _has_index(insp, "support_requests", "ix_support_requests_status_door"):
            op.drop_index("ix_support_requests_status_door", table_name="support_requests")
        if _has_index(insp, "support_requests", "ix_support_requests_tenant_status_created"):
            op.drop_index("ix_support_requests_tenant_status_created", table_name="support_requests")
        op.drop_table("support_requests")