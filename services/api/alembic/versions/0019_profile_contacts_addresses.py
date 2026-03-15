"""add workspace profile contacts and addresses

Revision ID: 0019_profile_contacts_v1
Revises: 0018_invoice_compliance_v1
Create Date: 2026-03-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0019_profile_contacts_v1"
down_revision = "0018_invoice_compliance_v1"
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

    if not _has_table(insp, "workspace_contact_points"):
        op.create_table(
            "workspace_contact_points",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("contact_kind", sa.String(length=32), nullable=False, server_default=sa.text("'GENERAL'")),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("website_url", sa.String(length=1024), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_contact_points") and not _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope"):
        op.create_index("ix_workspace_contact_scope", "workspace_contact_points", ["workspace_type", "workspace_id"], unique=False)
    if _has_table(insp, "workspace_contact_points") and not _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope_public"):
        op.create_index("ix_workspace_contact_scope_public", "workspace_contact_points", ["workspace_type", "workspace_id", "is_public"], unique=False)
    if _has_table(insp, "workspace_contact_points") and not _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope_primary"):
        op.create_index("ix_workspace_contact_scope_primary", "workspace_contact_points", ["workspace_type", "workspace_id", "is_primary"], unique=False)

    insp = sa.inspect(bind)
    if not _has_table(insp, "workspace_addresses"):
        op.create_table(
            "workspace_addresses",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("address_kind", sa.String(length=32), nullable=False, server_default=sa.text("'REGISTERED'")),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=True),
            sa.Column("line1", sa.String(length=255), nullable=True),
            sa.Column("line2", sa.String(length=255), nullable=True),
            sa.Column("city", sa.String(length=128), nullable=True),
            sa.Column("postal_code", sa.String(length=32), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_addresses") and not _has_index(insp, "workspace_addresses", "ix_workspace_address_scope"):
        op.create_index("ix_workspace_address_scope", "workspace_addresses", ["workspace_type", "workspace_id"], unique=False)
    if _has_table(insp, "workspace_addresses") and not _has_index(insp, "workspace_addresses", "ix_workspace_address_scope_public"):
        op.create_index("ix_workspace_address_scope_public", "workspace_addresses", ["workspace_type", "workspace_id", "is_public"], unique=False)
    if _has_table(insp, "workspace_addresses") and not _has_index(insp, "workspace_addresses", "ix_workspace_address_scope_primary"):
        op.create_index("ix_workspace_address_scope_primary", "workspace_addresses", ["workspace_type", "workspace_id", "is_primary"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "workspace_addresses"):
        if _has_index(insp, "workspace_addresses", "ix_workspace_address_scope_primary"):
            op.drop_index("ix_workspace_address_scope_primary", table_name="workspace_addresses")
        if _has_index(insp, "workspace_addresses", "ix_workspace_address_scope_public"):
            op.drop_index("ix_workspace_address_scope_public", table_name="workspace_addresses")
        if _has_index(insp, "workspace_addresses", "ix_workspace_address_scope"):
            op.drop_index("ix_workspace_address_scope", table_name="workspace_addresses")
        op.drop_table("workspace_addresses")

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_contact_points"):
        if _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope_primary"):
            op.drop_index("ix_workspace_contact_scope_primary", table_name="workspace_contact_points")
        if _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope_public"):
            op.drop_index("ix_workspace_contact_scope_public", table_name="workspace_contact_points")
        if _has_index(insp, "workspace_contact_points", "ix_workspace_contact_scope"):
            op.drop_index("ix_workspace_contact_scope", table_name="workspace_contact_points")
        op.drop_table("workspace_contact_points")
