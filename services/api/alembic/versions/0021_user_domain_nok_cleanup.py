"""align user domain schema: next-of-kin + remove company fields from users

Revision ID: 0021_user_domain_nok_cleanup
Revises: 0020_user_domain_v1
Create Date: 2026-03-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0021_user_domain_nok_cleanup"
down_revision = "0020_user_domain_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, idx_name: str) -> bool:
    try:
        return any(i.get("name") == idx_name for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_column(insp: sa.Inspector, table_name: str, col_name: str) -> bool:
    try:
        return any(c.get("name") == col_name for c in insp.get_columns(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "workspace_user_next_of_kin"):
        op.create_table(
            "workspace_user_next_of_kin",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=False),
            sa.Column("relation", sa.String(length=64), nullable=False),
            sa.Column("contact_email", sa.String(length=255), nullable=True),
            sa.Column("contact_phone", sa.String(length=64), nullable=True),
            sa.Column("address_country_code", sa.String(length=8), nullable=True),
            sa.Column("address_line1", sa.String(length=255), nullable=True),
            sa.Column("address_line2", sa.String(length=255), nullable=True),
            sa.Column("address_city", sa.String(length=128), nullable=True),
            sa.Column("address_postal_code", sa.String(length=32), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_next_of_kin") and not _has_index(insp, "workspace_user_next_of_kin", "ix_workspace_user_nok_scope"):
        op.create_index("ix_workspace_user_nok_scope", "workspace_user_next_of_kin", ["workspace_type", "workspace_id", "user_id"], unique=False)
    if _has_table(insp, "workspace_user_next_of_kin") and not _has_index(insp, "workspace_user_next_of_kin", "ix_workspace_user_nok_scope_primary"):
        op.create_index(
            "ix_workspace_user_nok_scope_primary",
            "workspace_user_next_of_kin",
            ["workspace_type", "workspace_id", "user_id", "is_primary"],
            unique=False,
        )

    if _has_table(insp, "workspace_user_profiles"):
        for col in [
            "legal_name",
            "vat_number",
            "registration_number",
            "legal_form_hint",
            "industry",
            "activity_summary",
            "presentation_text",
            "website_url",
        ]:
            if _has_column(insp, "workspace_user_profiles", col):
                op.drop_column("workspace_user_profiles", col)
                insp = sa.inspect(bind)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "workspace_user_profiles"):
        if not _has_column(insp, "workspace_user_profiles", "legal_name"):
            op.add_column("workspace_user_profiles", sa.Column("legal_name", sa.String(length=255), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "vat_number"):
            op.add_column("workspace_user_profiles", sa.Column("vat_number", sa.String(length=64), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "registration_number"):
            op.add_column("workspace_user_profiles", sa.Column("registration_number", sa.String(length=64), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "legal_form_hint"):
            op.add_column("workspace_user_profiles", sa.Column("legal_form_hint", sa.String(length=64), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "industry"):
            op.add_column("workspace_user_profiles", sa.Column("industry", sa.String(length=128), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "activity_summary"):
            op.add_column("workspace_user_profiles", sa.Column("activity_summary", sa.String(length=2000), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "presentation_text"):
            op.add_column("workspace_user_profiles", sa.Column("presentation_text", sa.String(length=5000), nullable=True))
        if not _has_column(insp, "workspace_user_profiles", "website_url"):
            op.add_column("workspace_user_profiles", sa.Column("website_url", sa.String(length=1024), nullable=True))

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_next_of_kin"):
        if _has_index(insp, "workspace_user_next_of_kin", "ix_workspace_user_nok_scope_primary"):
            op.drop_index("ix_workspace_user_nok_scope_primary", table_name="workspace_user_next_of_kin")
        if _has_index(insp, "workspace_user_next_of_kin", "ix_workspace_user_nok_scope"):
            op.drop_index("ix_workspace_user_nok_scope", table_name="workspace_user_next_of_kin")
        op.drop_table("workspace_user_next_of_kin")
