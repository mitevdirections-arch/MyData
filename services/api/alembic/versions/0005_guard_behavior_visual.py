"""add guard behavior policy state and license visual identity

Revision ID: 0005_guard_behavior_visual
Revises: 0004_storage_delete_queue
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_guard_behavior_visual"
down_revision = "0004_storage_delete_queue"
branch_labels = None
depends_on = None


def _has_column(insp, table_name: str, col: str) -> bool:
    return any(c.get("name") == col for c in insp.get_columns(table_name))


def _has_index(insp, table_name: str, idx: str) -> bool:
    return any(i.get("name") == idx for i in insp.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_column(insp, "tenants", "vat_number"):
        op.add_column("tenants", sa.Column("vat_number", sa.String(length=64), nullable=True))

    if not _has_column(insp, "licenses", "license_visual_code"):
        op.add_column("licenses", sa.Column("license_visual_code", sa.String(length=96), nullable=True))

    insp = sa.inspect(bind)
    if not _has_index(insp, "licenses", "ix_licenses_visual_code"):
        op.create_index("ix_licenses_visual_code", "licenses", ["license_visual_code"], unique=False)

    insp = sa.inspect(bind)
    if "guard_behavior_states" not in insp.get_table_names():
        op.create_table(
            "guard_behavior_states",
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("good_since", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("suspicion_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_suspicion_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_multiplier", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("recommended_interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("1800")),
            sa.Column("next_heartbeat_due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("session_open", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("last_event", sa.String(length=32), nullable=True),
            sa.Column("last_device_id", sa.String(length=128), nullable=True),
            sa.Column("last_status", sa.String(length=32), nullable=True),
            sa.Column("last_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    insp = sa.inspect(bind)
    if "guard_behavior_states" in insp.get_table_names() and not _has_index(insp, "guard_behavior_states", "ix_guard_behavior_due"):
        op.create_index(
            "ix_guard_behavior_due",
            "guard_behavior_states",
            ["session_open", "next_heartbeat_due_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "guard_behavior_states" in insp.get_table_names():
        if _has_index(insp, "guard_behavior_states", "ix_guard_behavior_due"):
            op.drop_index("ix_guard_behavior_due", table_name="guard_behavior_states")
        op.drop_table("guard_behavior_states")

    insp = sa.inspect(bind)
    if _has_index(insp, "licenses", "ix_licenses_visual_code"):
        op.drop_index("ix_licenses_visual_code", table_name="licenses")
    if _has_column(insp, "licenses", "license_visual_code"):
        op.drop_column("licenses", "license_visual_code")

    insp = sa.inspect(bind)
    if _has_column(insp, "tenants", "vat_number"):
        op.drop_column("tenants", "vat_number")