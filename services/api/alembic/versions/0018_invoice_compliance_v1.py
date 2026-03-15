"""add invoice compliance template foundation

Revision ID: 0018_invoice_compliance_v1
Revises: 0017_payments_deferred_v1
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0018_invoice_compliance_v1"
down_revision = "0017_payments_deferred_v1"
branch_labels = None
depends_on = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_col(inspector: sa.Inspector, table_name: str, col_name: str) -> bool:
    return any(c.get("name") == col_name for c in inspector.get_columns(table_name))


def _has_unique(inspector: sa.Inspector, table_name: str, uq_name: str) -> bool:
    return any(u.get("name") == uq_name for u in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "payment_invoice_sequences"):
        op.create_table(
            "payment_invoice_sequences",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("next_serial", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("tenant_id", name="uq_payment_invoice_seq_tenant"),
        )

    if _has_table(insp, "payment_invoices") and not _has_col(insp, "payment_invoices", "invoice_no"):
        op.add_column(
            "payment_invoices",
            sa.Column(
                "invoice_no",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("CONCAT('INV-', REPLACE(gen_random_uuid()::STRING, '-', ''))"),
            ),
        )

    if _has_table(insp, "payment_invoices") and not _has_col(insp, "payment_invoices", "template_code"):
        op.add_column(
            "payment_invoices",
            sa.Column("template_code", sa.String(length=32), nullable=False, server_default="EU_VAT_V1"),
        )

    if _has_table(insp, "payment_invoices") and not _has_col(insp, "payment_invoices", "compliance_json"):
        op.add_column(
            "payment_invoices",
            sa.Column("compliance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "payment_invoices"):
        if _has_unique(insp, "payment_invoices", "uq_payment_invoice_tenant_no"):
            op.drop_constraint("uq_payment_invoice_tenant_no", "payment_invoices", type_="unique")
        if _has_col(insp, "payment_invoices", "compliance_json"):
            op.drop_column("payment_invoices", "compliance_json")
        if _has_col(insp, "payment_invoices", "template_code"):
            op.drop_column("payment_invoices", "template_code")
        if _has_col(insp, "payment_invoices", "invoice_no"):
            op.drop_column("payment_invoices", "invoice_no")

    insp = sa.inspect(bind)
    if _has_table(insp, "payment_invoice_sequences"):
        op.drop_table("payment_invoice_sequences")
