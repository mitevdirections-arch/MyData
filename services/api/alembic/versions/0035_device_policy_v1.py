"""device policy v1 enforcement foundation

Revision ID: 0035_device_policy_v1
Revises: 0034_entity_verification_v1
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_device_policy_v1"
down_revision = "0034_entity_verification_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_column(insp: sa.Inspector, table_name: str, column_name: str) -> bool:
    try:
        cols = insp.get_columns(table_name)
    except Exception:  # noqa: BLE001
        return False
    return any(str(col.get("name")) == column_name for col in cols)


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(str(idx.get("name")) == index_name for idx in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_unique(insp: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    try:
        return any(str(uc.get("name")) == constraint_name for uc in insp.get_unique_constraints(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "device_leases"):
        raise RuntimeError("device_leases_table_missing_before_0035")

    if not _has_column(insp, "device_leases", "state"):
        op.add_column(
            "device_leases",
            sa.Column("state", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
        )
    if not _has_column(insp, "device_leases", "state_changed_at"):
        op.add_column(
            "device_leases",
            sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if not _has_column(insp, "device_leases", "last_live_at"):
        op.add_column(
            "device_leases",
            sa.Column("last_live_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if not _has_column(insp, "device_leases", "paused_at"):
        op.add_column("device_leases", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(insp, "device_leases", "background_reachable_at"):
        op.add_column("device_leases", sa.Column("background_reachable_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(insp, "device_leases", "logged_out_at"):
        op.add_column("device_leases", sa.Column("logged_out_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(insp, "device_leases", "revoked_at"):
        op.add_column("device_leases", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))

    insp = sa.inspect(bind)
    if _has_unique(insp, "device_leases", "uq_device_lease_tenant_user") or _has_index(insp, "device_leases", "uq_device_lease_tenant_user"):
        op.execute(sa.text("DROP INDEX IF EXISTS uq_device_lease_tenant_user CASCADE"))

    insp = sa.inspect(bind)
    if not _has_unique(insp, "device_leases", "uq_device_lease_tenant_user_class") and not _has_index(insp, "device_leases", "uq_device_lease_tenant_user_class"):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_lease_tenant_user_class "
                "ON device_leases (tenant_id, user_id, device_class)"
            )
        )

    insp = sa.inspect(bind)
    if not _has_index(insp, "device_leases", "ix_device_lease_tenant_user_state"):
        op.create_index("ix_device_lease_tenant_user_state", "device_leases", ["tenant_id", "user_id", "state"], unique=False)
    if not _has_index(insp, "device_leases", "ix_device_lease_tenant_device"):
        op.create_index("ix_device_lease_tenant_device", "device_leases", ["tenant_id", "device_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "device_leases"):
        return

    if _has_index(insp, "device_leases", "ix_device_lease_tenant_device"):
        op.drop_index("ix_device_lease_tenant_device", table_name="device_leases")
    if _has_index(insp, "device_leases", "ix_device_lease_tenant_user_state"):
        op.drop_index("ix_device_lease_tenant_user_state", table_name="device_leases")

    insp = sa.inspect(bind)
    if _has_unique(insp, "device_leases", "uq_device_lease_tenant_user_class") or _has_index(insp, "device_leases", "uq_device_lease_tenant_user_class"):
        op.execute(sa.text("DROP INDEX IF EXISTS uq_device_lease_tenant_user_class CASCADE"))

    insp = sa.inspect(bind)
    if not _has_unique(insp, "device_leases", "uq_device_lease_tenant_user") and not _has_index(insp, "device_leases", "uq_device_lease_tenant_user"):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_lease_tenant_user "
                "ON device_leases (tenant_id, user_id)"
            )
        )

    # Keep historic state columns on downgrade to avoid destructive data loss.
