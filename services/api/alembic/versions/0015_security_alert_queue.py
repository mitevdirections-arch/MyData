"""add security alert queue table

Revision ID: 0015_security_alert_queue
Revises: 0014_marketplace_foundation
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_security_alert_queue"
down_revision = "0014_marketplace_foundation"
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

    if "security_alert_queue" not in insp.get_table_names():
        op.create_table(
            "security_alert_queue",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False, server_default=sa.text("'LOG'")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("8")),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_error", sa.String(length=2000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "security_alert_queue" in insp.get_table_names() and not _has_index(insp, "security_alert_queue", "ix_security_alert_queue_status_next"):
        op.create_index("ix_security_alert_queue_status_next", "security_alert_queue", ["status", "next_attempt_at"], unique=False)
    if "security_alert_queue" in insp.get_table_names() and not _has_index(insp, "security_alert_queue", "ix_security_alert_queue_incident"):
        op.create_index("ix_security_alert_queue_incident", "security_alert_queue", ["incident_id", "status"], unique=False)
    if "security_alert_queue" in insp.get_table_names() and not _has_index(insp, "security_alert_queue", "ix_security_alert_queue_tenant_status"):
        op.create_index("ix_security_alert_queue_tenant_status", "security_alert_queue", ["tenant_id", "status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "security_alert_queue" in insp.get_table_names():
        if _has_index(insp, "security_alert_queue", "ix_security_alert_queue_tenant_status"):
            op.drop_index("ix_security_alert_queue_tenant_status", table_name="security_alert_queue")
        if _has_index(insp, "security_alert_queue", "ix_security_alert_queue_incident"):
            op.drop_index("ix_security_alert_queue_incident", table_name="security_alert_queue")
        if _has_index(insp, "security_alert_queue", "ix_security_alert_queue_status_next"):
            op.drop_index("ix_security_alert_queue_status_next", table_name="security_alert_queue")
        op.drop_table("security_alert_queue")