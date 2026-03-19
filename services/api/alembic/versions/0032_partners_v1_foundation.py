"""partners v1 backend foundation

Revision ID: 0032_partners_v1_foundation
Revises: 0031_eidon_runtime_enable_v1
Create Date: 2026-03-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0032_partners_v1_foundation"
down_revision = "0031_eidon_runtime_enable_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "global_companies"):
        op.create_table(
            "global_companies",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("canonical_name", sa.String(length=255), nullable=False),
            sa.Column("legal_name", sa.String(length=255), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=False),
            sa.Column("vat_number", sa.String(length=64), nullable=True),
            sa.Column("registration_number", sa.String(length=64), nullable=True),
            sa.Column("website_url", sa.String(length=512), nullable=True),
            sa.Column("main_email", sa.String(length=255), nullable=True),
            sa.Column("main_phone", sa.String(length=64), nullable=True),
            sa.Column("normalized_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_global_companies_country_vat
        ON global_companies (country_code, vat_number)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_global_companies_country_registration
        ON global_companies (country_code, registration_number)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_global_companies_country_normalized_name
        ON global_companies (country_code, normalized_name)
        """
    )

    if not _has_table(insp, "global_company_reputation"):
        op.create_table(
            "global_company_reputation",
            sa.Column("global_company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("total_tenants", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_completed_orders_rated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_execution_quality", sa.Float(), nullable=True),
            sa.Column("avg_communication_docs", sa.Float(), nullable=True),
            sa.Column("avg_payment_discipline", sa.Float(), nullable=True),
            sa.Column("global_overall_score", sa.Float(), nullable=True),
            sa.Column("risk_payment_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("risk_quality_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blacklist_signal_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["global_company_id"], ["global_companies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("global_company_id"),
        )

    if not _has_table(insp, "tenant_partners"):
        op.create_table(
            "tenant_partners",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("global_company_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("partner_code", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("legal_name", sa.String(length=255), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=False),
            sa.Column("vat_number", sa.String(length=64), nullable=True),
            sa.Column("registration_number", sa.String(length=64), nullable=True),
            sa.Column("website_url", sa.String(length=512), nullable=True),
            sa.Column("main_email", sa.String(length=255), nullable=True),
            sa.Column("main_phone", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("is_blacklisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_watchlisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("blacklist_reason", sa.String(length=1024), nullable=True),
            sa.Column("internal_note", sa.String(length=4000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["global_company_id"], ["global_companies.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "partner_code", name="uq_tenant_partner_company_code"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partners_company_status_updated
        ON tenant_partners (company_id, status, updated_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partners_company_global
        ON tenant_partners (company_id, global_company_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partners_company_vat
        ON tenant_partners (company_id, country_code, vat_number)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partners_company_registration
        ON tenant_partners (company_id, country_code, registration_number)
        """
    )

    if not _has_table(insp, "tenant_partner_roles"):
        op.create_table(
            "tenant_partner_roles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role_code", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("partner_id", "role_code", name="uq_tenant_partner_role"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_roles_partner
        ON tenant_partner_roles (partner_id)
        """
    )

    if not _has_table(insp, "tenant_partner_addresses"):
        op.create_table(
            "tenant_partner_addresses",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("address_type", sa.String(length=32), nullable=False, server_default="HQ"),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=True),
            sa.Column("line1", sa.String(length=255), nullable=True),
            sa.Column("line2", sa.String(length=255), nullable=True),
            sa.Column("city", sa.String(length=128), nullable=True),
            sa.Column("postal_code", sa.String(length=32), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_addresses_company_partner
        ON tenant_partner_addresses (company_id, partner_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_addresses_partner_primary
        ON tenant_partner_addresses (partner_id, is_primary)
        """
    )

    if not _has_table(insp, "tenant_partner_bank_accounts"):
        op.create_table(
            "tenant_partner_bank_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("account_holder", sa.String(length=255), nullable=True),
            sa.Column("iban", sa.String(length=64), nullable=True),
            sa.Column("swift", sa.String(length=32), nullable=True),
            sa.Column("bank_name", sa.String(length=255), nullable=True),
            sa.Column("bank_country_code", sa.String(length=8), nullable=True),
            sa.Column("currency", sa.String(length=16), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("note", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_bank_company_partner
        ON tenant_partner_bank_accounts (company_id, partner_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_bank_partner_primary
        ON tenant_partner_bank_accounts (partner_id, is_primary)
        """
    )

    if not _has_table(insp, "tenant_partner_contacts"):
        op.create_table(
            "tenant_partner_contacts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("contact_name", sa.String(length=255), nullable=False),
            sa.Column("contact_role", sa.String(length=128), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("note", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_contacts_company_partner
        ON tenant_partner_contacts (company_id, partner_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_contacts_partner_primary
        ON tenant_partner_contacts (partner_id, is_primary)
        """
    )

    if not _has_table(insp, "tenant_partner_documents"):
        op.create_table(
            "tenant_partner_documents",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("doc_type", sa.String(length=64), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("storage_key", sa.String(length=512), nullable=False),
            sa.Column("uploaded_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("note", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_documents_company_partner
        ON tenant_partner_documents (company_id, partner_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_partner_documents_partner_doc_type
        ON tenant_partner_documents (partner_id, doc_type)
        """
    )

    if not _has_table(insp, "partner_order_ratings"):
        op.create_table(
            "partner_order_ratings",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("company_id", sa.String(length=64), nullable=False),
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("rated_by_user_id", sa.String(length=255), nullable=False),
            sa.Column("execution_quality_stars", sa.Integer(), nullable=False),
            sa.Column("communication_docs_stars", sa.Integer(), nullable=False),
            sa.Column("payment_discipline_stars", sa.Integer(), nullable=True),
            sa.Column("payment_expected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("short_comment", sa.String(length=2000), nullable=True),
            sa.Column("issue_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("execution_quality_stars BETWEEN 1 AND 6", name="ck_partner_rating_execution_stars"),
            sa.CheckConstraint("communication_docs_stars BETWEEN 1 AND 6", name="ck_partner_rating_communication_stars"),
            sa.CheckConstraint(
                "(payment_discipline_stars IS NULL) OR (payment_discipline_stars BETWEEN 1 AND 6)",
                name="ck_partner_rating_payment_stars_range",
            ),
            sa.CheckConstraint(
                "(payment_expected = false AND payment_discipline_stars IS NULL) OR "
                "(payment_expected = true AND payment_discipline_stars IS NOT NULL)",
                name="ck_partner_rating_payment_expected_contract",
            ),
            sa.ForeignKeyConstraint(["company_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_partner_order_ratings_company_partner_created
        ON partner_order_ratings (company_id, partner_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_partner_order_ratings_company_order
        ON partner_order_ratings (company_id, order_id)
        """
    )

    if not _has_table(insp, "tenant_partner_rating_summary"):
        op.create_table(
            "tenant_partner_rating_summary",
            sa.Column("partner_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_execution_quality", sa.Float(), nullable=True),
            sa.Column("avg_communication_docs", sa.Float(), nullable=True),
            sa.Column("avg_payment_discipline", sa.Float(), nullable=True),
            sa.Column("avg_overall_score", sa.Float(), nullable=True),
            sa.Column("last_rating_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payment_issue_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["partner_id"], ["tenant_partners.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("partner_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "tenant_partner_rating_summary"):
        op.drop_table("tenant_partner_rating_summary")

    if _has_table(insp, "partner_order_ratings"):
        op.drop_index("ix_partner_order_ratings_company_order", table_name="partner_order_ratings")
        op.drop_index("ix_partner_order_ratings_company_partner_created", table_name="partner_order_ratings")
        op.drop_table("partner_order_ratings")

    if _has_table(insp, "tenant_partner_documents"):
        op.drop_index("ix_tenant_partner_documents_partner_doc_type", table_name="tenant_partner_documents")
        op.drop_index("ix_tenant_partner_documents_company_partner", table_name="tenant_partner_documents")
        op.drop_table("tenant_partner_documents")

    if _has_table(insp, "tenant_partner_contacts"):
        op.drop_index("ix_tenant_partner_contacts_partner_primary", table_name="tenant_partner_contacts")
        op.drop_index("ix_tenant_partner_contacts_company_partner", table_name="tenant_partner_contacts")
        op.drop_table("tenant_partner_contacts")

    if _has_table(insp, "tenant_partner_bank_accounts"):
        op.drop_index("ix_tenant_partner_bank_partner_primary", table_name="tenant_partner_bank_accounts")
        op.drop_index("ix_tenant_partner_bank_company_partner", table_name="tenant_partner_bank_accounts")
        op.drop_table("tenant_partner_bank_accounts")

    if _has_table(insp, "tenant_partner_addresses"):
        op.drop_index("ix_tenant_partner_addresses_partner_primary", table_name="tenant_partner_addresses")
        op.drop_index("ix_tenant_partner_addresses_company_partner", table_name="tenant_partner_addresses")
        op.drop_table("tenant_partner_addresses")

    if _has_table(insp, "tenant_partner_roles"):
        op.drop_index("ix_tenant_partner_roles_partner", table_name="tenant_partner_roles")
        op.drop_table("tenant_partner_roles")

    if _has_table(insp, "tenant_partners"):
        op.drop_index("ix_tenant_partners_company_registration", table_name="tenant_partners")
        op.drop_index("ix_tenant_partners_company_vat", table_name="tenant_partners")
        op.drop_index("ix_tenant_partners_company_global", table_name="tenant_partners")
        op.drop_index("ix_tenant_partners_company_status_updated", table_name="tenant_partners")
        op.drop_table("tenant_partners")

    if _has_table(insp, "global_company_reputation"):
        op.drop_table("global_company_reputation")

    if _has_table(insp, "global_companies"):
        op.drop_index("ix_global_companies_country_normalized_name", table_name="global_companies")
        op.drop_index("ix_global_companies_country_registration", table_name="global_companies")
        op.drop_index("ix_global_companies_country_vat", table_name="global_companies")
        op.drop_table("global_companies")
