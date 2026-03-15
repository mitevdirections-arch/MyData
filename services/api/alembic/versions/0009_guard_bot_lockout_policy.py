"""add guard bot lockout policy columns

Revision ID: 0009_guard_bot_lockout_policy
Revises: 0008_guard_bot_crypto_controls
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_guard_bot_lockout_policy"
down_revision = "0008_guard_bot_crypto_controls"
branch_labels = None
depends_on = None


def _has_column(insp, table_name: str, column_name: str) -> bool:
    try:
        return any(c.get("name") == column_name for c in insp.get_columns(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "guard_bot_credentials" not in insp.get_table_names():
        return

    if not _has_column(insp, "guard_bot_credentials", "failed_attempts"):
        op.add_column("guard_bot_credentials", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    if not _has_column(insp, "guard_bot_credentials", "locked_until"):
        op.add_column("guard_bot_credentials", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(insp, "guard_bot_credentials", "last_failed_at"):
        op.add_column("guard_bot_credentials", sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(insp, "guard_bot_credentials", "last_fail_reason"):
        op.add_column("guard_bot_credentials", sa.Column("last_fail_reason", sa.String(length=512), nullable=True))
    if not _has_column(insp, "guard_bot_credentials", "last_warning_at"):
        op.add_column("guard_bot_credentials", sa.Column("last_warning_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "guard_bot_credentials" not in insp.get_table_names():
        return

    if _has_column(insp, "guard_bot_credentials", "last_warning_at"):
        op.drop_column("guard_bot_credentials", "last_warning_at")
    if _has_column(insp, "guard_bot_credentials", "last_fail_reason"):
        op.drop_column("guard_bot_credentials", "last_fail_reason")
    if _has_column(insp, "guard_bot_credentials", "last_failed_at"):
        op.drop_column("guard_bot_credentials", "last_failed_at")
    if _has_column(insp, "guard_bot_credentials", "locked_until"):
        op.drop_column("guard_bot_credentials", "locked_until")
    if _has_column(insp, "guard_bot_credentials", "failed_attempts"):
        op.drop_column("guard_bot_credentials", "failed_attempts")