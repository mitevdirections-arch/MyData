"""add guard bot checks table

Revision ID: 0006_guard_bot_checks
Revises: 0005_guard_behavior_visual
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_guard_bot_checks"
down_revision = "0005_guard_behavior_visual"
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

    if "guard_bot_checks" not in insp.get_table_names():
        op.create_table(
            "guard_bot_checks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("bot_id", sa.String(length=128), nullable=False, server_default=sa.text("'guard-bot'")),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default=sa.text("'SCHEDULED'")),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("missing_heartbeat", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("stale_heartbeat", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("bad_status", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("stale_enforced", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("notes", sa.String(length=512), nullable=True),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "guard_bot_checks" in insp.get_table_names():
        if not _has_index(insp, "guard_bot_checks", "ix_guard_bot_checks_tenant_checked"):
            op.create_index("ix_guard_bot_checks_tenant_checked", "guard_bot_checks", ["tenant_id", "checked_at"], unique=False)
        if not _has_index(insp, "guard_bot_checks", "ix_guard_bot_checks_run_checked"):
            op.create_index("ix_guard_bot_checks_run_checked", "guard_bot_checks", ["run_id", "checked_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "guard_bot_checks" in insp.get_table_names():
        if _has_index(insp, "guard_bot_checks", "ix_guard_bot_checks_run_checked"):
            op.drop_index("ix_guard_bot_checks_run_checked", table_name="guard_bot_checks")
        if _has_index(insp, "guard_bot_checks", "ix_guard_bot_checks_tenant_checked"):
            op.drop_index("ix_guard_bot_checks_tenant_checked", table_name="guard_bot_checks")
        op.drop_table("guard_bot_checks")