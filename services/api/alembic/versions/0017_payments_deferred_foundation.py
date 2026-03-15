"""add payments deferred foundation

Revision ID: 0017_payments_deferred_v1
Revises: 0016_orders_foundation
Create Date: 2026-03-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_payments_deferred_v1"
down_revision = "0016_orders_foundation"
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

    if "tenant_credit_accounts" not in insp.get_table_names():
        op.create_table(
            "tenant_credit_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payment_mode", sa.String(length=16), nullable=False, server_default=sa.text("'PREPAID'")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("credit_limit_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default=sa.text("'EUR'")),
            sa.Column("terms_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
            sa.Column("grace_days", sa.Integer(), nullable=False, server_default=sa.text("3")),
            sa.Column("auto_hold_on_overdue", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("overdue_hold", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "tenant_credit_accounts" in insp.get_table_names() and not _has_unique(insp, "tenant_credit_accounts", "uq_credit_account_tenant"):
        op.create_unique_constraint("uq_credit_account_tenant", "tenant_credit_accounts", ["tenant_id"])
    if "tenant_credit_accounts" in insp.get_table_names() and not _has_index(insp, "tenant_credit_accounts", "ix_credit_account_mode_status"):
        op.create_index("ix_credit_account_mode_status", "tenant_credit_accounts", ["payment_mode", "status"], unique=False)

    insp = sa.inspect(bind)
    if "payment_invoices" not in insp.get_table_names():
        op.create_table(
            "payment_invoices",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("source_ref", sa.String(length=128), nullable=True),
            sa.Column("module_code", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'ISSUED'")),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default=sa.text("'EUR'")),
            sa.Column("amount_minor", sa.Integer(), nullable=False),
            sa.Column("description", sa.String(length=1024), nullable=True),
            sa.Column("issue_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "payment_invoices" in insp.get_table_names() and not _has_index(insp, "payment_invoices", "ix_payment_invoice_tenant_status_due"):
        op.create_index("ix_payment_invoice_tenant_status_due", "payment_invoices", ["tenant_id", "status", "due_at"], unique=False)
    if "payment_invoices" in insp.get_table_names() and not _has_index(insp, "payment_invoices", "ix_payment_invoice_source"):
        op.create_index("ix_payment_invoice_source", "payment_invoices", ["source_type", "source_ref"], unique=False)

    insp = sa.inspect(bind)
    if "payment_allocations" not in insp.get_table_names():
        op.create_table(
            "payment_allocations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_invoices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("amount_minor", sa.Integer(), nullable=False),
            sa.Column("method", sa.String(length=32), nullable=False, server_default=sa.text("'MANUAL'")),
            sa.Column("reference", sa.String(length=255), nullable=True),
            sa.Column("paid_by", sa.String(length=255), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "payment_allocations" in insp.get_table_names() and not _has_index(insp, "payment_allocations", "ix_payment_alloc_invoice_paid"):
        op.create_index("ix_payment_alloc_invoice_paid", "payment_allocations", ["invoice_id", "paid_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "payment_allocations" in insp.get_table_names():
        if _has_index(insp, "payment_allocations", "ix_payment_alloc_invoice_paid"):
            op.drop_index("ix_payment_alloc_invoice_paid", table_name="payment_allocations")
        op.drop_table("payment_allocations")

    insp = sa.inspect(bind)
    if "payment_invoices" in insp.get_table_names():
        if _has_index(insp, "payment_invoices", "ix_payment_invoice_source"):
            op.drop_index("ix_payment_invoice_source", table_name="payment_invoices")
        if _has_index(insp, "payment_invoices", "ix_payment_invoice_tenant_status_due"):
            op.drop_index("ix_payment_invoice_tenant_status_due", table_name="payment_invoices")
        op.drop_table("payment_invoices")

    insp = sa.inspect(bind)
    if "tenant_credit_accounts" in insp.get_table_names():
        if _has_index(insp, "tenant_credit_accounts", "ix_credit_account_mode_status"):
            op.drop_index("ix_credit_account_mode_status", table_name="tenant_credit_accounts")
        if _has_unique(insp, "tenant_credit_accounts", "uq_credit_account_tenant"):
            op.drop_constraint("uq_credit_account_tenant", "tenant_credit_accounts", type_="unique")
        op.drop_table("tenant_credit_accounts")