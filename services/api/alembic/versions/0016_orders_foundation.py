"""add orders foundation table

Revision ID: 0016_orders_foundation
Revises: 0015_security_alert_queue
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_orders_foundation"
down_revision = "0015_security_alert_queue"
branch_labels = None
depends_on = None


def _has_index(insp, table_name: str, idx: str) -> bool:
    try:
        return any(i.get("name") == idx for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_unique(insp, table_name: str, uq: str) -> bool:
    try:
        return any(i.get("name") == uq for i in insp.get_unique_constraints(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "orders" not in insp.get_table_names():
        op.create_table(
            "orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("order_no", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'DRAFT'")),
            sa.Column("transport_mode", sa.String(length=16), nullable=False, server_default=sa.text("'ROAD'")),
            sa.Column("direction", sa.String(length=16), nullable=False, server_default=sa.text("'OUTBOUND'")),
            sa.Column("customer_name", sa.String(length=255), nullable=True),
            sa.Column("pickup_location", sa.String(length=255), nullable=True),
            sa.Column("delivery_location", sa.String(length=255), nullable=True),
            sa.Column("cargo_description", sa.String(length=2000), nullable=True),
            sa.Column("reference_no", sa.String(length=128), nullable=True),
            sa.Column("scheduled_pickup_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scheduled_delivery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "orders" in insp.get_table_names() and not _has_unique(insp, "orders", "uq_orders_tenant_order_no"):
        op.create_unique_constraint("uq_orders_tenant_order_no", "orders", ["tenant_id", "order_no"])
    if "orders" in insp.get_table_names() and not _has_index(insp, "orders", "ix_orders_tenant_status_created"):
        op.create_index("ix_orders_tenant_status_created", "orders", ["tenant_id", "status", "created_at"], unique=False)
    if "orders" in insp.get_table_names() and not _has_index(insp, "orders", "ix_orders_tenant_mode_created"):
        op.create_index("ix_orders_tenant_mode_created", "orders", ["tenant_id", "transport_mode", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "orders" in insp.get_table_names():
        if _has_index(insp, "orders", "ix_orders_tenant_mode_created"):
            op.drop_index("ix_orders_tenant_mode_created", table_name="orders")
        if _has_index(insp, "orders", "ix_orders_tenant_status_created"):
            op.drop_index("ix_orders_tenant_status_created", table_name="orders")
        if _has_unique(insp, "orders", "uq_orders_tenant_order_no"):
            op.drop_constraint("uq_orders_tenant_order_no", "orders", type_="unique")
        op.drop_table("orders")