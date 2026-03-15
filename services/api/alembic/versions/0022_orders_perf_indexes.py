"""orders list path hardening indexes

Revision ID: 0022_orders_perf_indexes
Revises: 0021_user_domain_nok_cleanup
Create Date: 2026-03-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_orders_perf_indexes"
down_revision = "0021_user_domain_nok_cleanup"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, idx_name: str) -> bool:
    try:
        return any(i.get("name") == idx_name for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "orders") and not _has_index(insp, "orders", "ix_orders_tenant_created"):
        op.create_index("ix_orders_tenant_created", "orders", ["tenant_id", "created_at"], unique=False)

    if _has_table(insp, "orders") and not _has_index(insp, "orders", "ix_orders_tenant_status_created"):
        op.create_index("ix_orders_tenant_status_created", "orders", ["tenant_id", "status", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "orders") and _has_index(insp, "orders", "ix_orders_tenant_created"):
        op.drop_index("ix_orders_tenant_created", table_name="orders")
