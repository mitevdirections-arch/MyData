"""add workspace user domain foundation

Revision ID: 0020_user_domain_v1
Revises: 0019_profile_contacts_v1
Create Date: 2026-03-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0020_user_domain_v1"
down_revision = "0019_profile_contacts_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, idx_name: str) -> bool:
    try:
        return any(i.get("name") == idx_name for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_unique(insp: sa.Inspector, table_name: str, uq_name: str) -> bool:
    try:
        return any(u.get("name") == uq_name for u in insp.get_unique_constraints(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "workspace_user_profiles"):
        op.create_table(
            "workspace_user_profiles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=128), nullable=True),
            sa.Column("last_name", sa.String(length=128), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("date_of_birth", sa.DateTime(timezone=True), nullable=True),
            sa.Column("legal_name", sa.String(length=255), nullable=True),
            sa.Column("vat_number", sa.String(length=64), nullable=True),
            sa.Column("registration_number", sa.String(length=64), nullable=True),
            sa.Column("legal_form_hint", sa.String(length=64), nullable=True),
            sa.Column("industry", sa.String(length=128), nullable=True),
            sa.Column("activity_summary", sa.String(length=2000), nullable=True),
            sa.Column("presentation_text", sa.String(length=5000), nullable=True),
            sa.Column("contact_email", sa.String(length=255), nullable=True),
            sa.Column("contact_phone", sa.String(length=64), nullable=True),
            sa.Column("website_url", sa.String(length=1024), nullable=True),
            sa.Column("address_country_code", sa.String(length=8), nullable=True),
            sa.Column("address_line1", sa.String(length=255), nullable=True),
            sa.Column("address_line2", sa.String(length=255), nullable=True),
            sa.Column("address_city", sa.String(length=128), nullable=True),
            sa.Column("address_postal_code", sa.String(length=32), nullable=True),
            sa.Column("bank_account_holder", sa.String(length=255), nullable=True),
            sa.Column("bank_iban", sa.String(length=64), nullable=True),
            sa.Column("bank_swift", sa.String(length=32), nullable=True),
            sa.Column("bank_name", sa.String(length=255), nullable=True),
            sa.Column("bank_currency", sa.String(length=16), nullable=True),
            sa.Column("employee_code", sa.String(length=64), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=True),
            sa.Column("department", sa.String(length=128), nullable=True),
            sa.Column("employment_status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("preferred_locale", sa.String(length=32), nullable=True),
            sa.Column("preferred_time_zone", sa.String(length=64), nullable=True),
            sa.Column("date_style", sa.String(length=8), nullable=True),
            sa.Column("time_style", sa.String(length=8), nullable=True),
            sa.Column("unit_system", sa.String(length=16), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_profiles") and not _has_unique(insp, "workspace_user_profiles", "uq_workspace_user_profile_scope_user"):
        op.create_unique_constraint("uq_workspace_user_profile_scope_user", "workspace_user_profiles", ["workspace_type", "workspace_id", "user_id"])
    if _has_table(insp, "workspace_user_profiles") and not _has_index(insp, "workspace_user_profiles", "ix_workspace_user_profile_scope"):
        op.create_index("ix_workspace_user_profile_scope", "workspace_user_profiles", ["workspace_type", "workspace_id"], unique=False)
    if _has_table(insp, "workspace_user_profiles") and not _has_index(insp, "workspace_user_profiles", "ix_workspace_user_profile_scope_user"):
        op.create_index("ix_workspace_user_profile_scope_user", "workspace_user_profiles", ["workspace_type", "workspace_id", "user_id"], unique=False)

    if not _has_table(insp, "workspace_user_contact_channels"):
        op.create_table(
            "workspace_user_contact_channels",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("channel_type", sa.String(length=32), nullable=False, server_default=sa.text("'EMAIL'")),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("value", sa.String(length=255), nullable=False),
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
    for idx, cols in [
        ("ix_workspace_user_contact_scope", ["workspace_type", "workspace_id", "user_id"]),
        ("ix_workspace_user_contact_scope_public", ["workspace_type", "workspace_id", "user_id", "is_public"]),
        ("ix_workspace_user_contact_scope_primary", ["workspace_type", "workspace_id", "user_id", "is_primary"]),
        ("ix_workspace_user_contact_scope_type", ["workspace_type", "workspace_id", "user_id", "channel_type"]),
    ]:
        if _has_table(insp, "workspace_user_contact_channels") and not _has_index(insp, "workspace_user_contact_channels", idx):
            op.create_index(idx, "workspace_user_contact_channels", cols, unique=False)

    if not _has_table(insp, "workspace_user_addresses"):
        op.create_table(
            "workspace_user_addresses",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("address_kind", sa.String(length=32), nullable=False, server_default=sa.text("'HOME'")),
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
    for idx, cols in [
        ("ix_workspace_user_address_scope", ["workspace_type", "workspace_id", "user_id"]),
        ("ix_workspace_user_address_scope_public", ["workspace_type", "workspace_id", "user_id", "is_public"]),
        ("ix_workspace_user_address_scope_primary", ["workspace_type", "workspace_id", "user_id", "is_primary"]),
    ]:
        if _has_table(insp, "workspace_user_addresses") and not _has_index(insp, "workspace_user_addresses", idx):
            op.create_index(idx, "workspace_user_addresses", cols, unique=False)

    if not _has_table(insp, "workspace_user_documents"):
        op.create_table(
            "workspace_user_documents",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("doc_kind", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("doc_number", sa.String(length=128), nullable=True),
            sa.Column("issuer", sa.String(length=255), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=True),
            sa.Column("issued_on", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("storage_provider", sa.String(length=32), nullable=True),
            sa.Column("bucket", sa.String(length=128), nullable=True),
            sa.Column("object_key", sa.String(length=512), nullable=True),
            sa.Column("file_name", sa.String(length=255), nullable=True),
            sa.Column("mime_type", sa.String(length=128), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("sha256", sa.String(length=128), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    for idx, cols in [
        ("ix_workspace_user_doc_scope", ["workspace_type", "workspace_id", "user_id"]),
        ("ix_workspace_user_doc_scope_kind", ["workspace_type", "workspace_id", "user_id", "doc_kind"]),
        ("ix_workspace_user_doc_scope_valid_until", ["workspace_type", "workspace_id", "user_id", "valid_until"]),
    ]:
        if _has_table(insp, "workspace_user_documents") and not _has_index(insp, "workspace_user_documents", idx):
            op.create_index(idx, "workspace_user_documents", cols, unique=False)

    if not _has_table(insp, "workspace_user_credentials"):
        op.create_table(
            "workspace_user_credentials",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("password_salt", sa.String(length=256), nullable=False),
            sa.Column("hash_alg", sa.String(length=32), nullable=False, server_default=sa.text("'PBKDF2_SHA256'")),
            sa.Column("hash_iterations", sa.Integer(), nullable=False, server_default=sa.text("210000")),
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_credentials") and not _has_unique(insp, "workspace_user_credentials", "uq_workspace_user_cred_scope_user"):
        op.create_unique_constraint("uq_workspace_user_cred_scope_user", "workspace_user_credentials", ["workspace_type", "workspace_id", "user_id"])
    if _has_table(insp, "workspace_user_credentials") and not _has_unique(insp, "workspace_user_credentials", "uq_workspace_user_cred_scope_username"):
        op.create_unique_constraint("uq_workspace_user_cred_scope_username", "workspace_user_credentials", ["workspace_type", "workspace_id", "username"])
    if _has_table(insp, "workspace_user_credentials") and not _has_index(insp, "workspace_user_credentials", "ix_workspace_user_cred_scope"):
        op.create_index("ix_workspace_user_cred_scope", "workspace_user_credentials", ["workspace_type", "workspace_id"], unique=False)
    if _has_table(insp, "workspace_user_credentials") and not _has_index(insp, "workspace_user_credentials", "ix_workspace_user_cred_scope_status"):
        op.create_index("ix_workspace_user_cred_scope_status", "workspace_user_credentials", ["workspace_type", "workspace_id", "status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "workspace_user_credentials"):
        if _has_index(insp, "workspace_user_credentials", "ix_workspace_user_cred_scope_status"):
            op.drop_index("ix_workspace_user_cred_scope_status", table_name="workspace_user_credentials")
        if _has_index(insp, "workspace_user_credentials", "ix_workspace_user_cred_scope"):
            op.drop_index("ix_workspace_user_cred_scope", table_name="workspace_user_credentials")
        if _has_unique(insp, "workspace_user_credentials", "uq_workspace_user_cred_scope_username"):
            op.drop_constraint("uq_workspace_user_cred_scope_username", "workspace_user_credentials", type_="unique")
        if _has_unique(insp, "workspace_user_credentials", "uq_workspace_user_cred_scope_user"):
            op.drop_constraint("uq_workspace_user_cred_scope_user", "workspace_user_credentials", type_="unique")
        op.drop_table("workspace_user_credentials")

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_documents"):
        for idx in ["ix_workspace_user_doc_scope_valid_until", "ix_workspace_user_doc_scope_kind", "ix_workspace_user_doc_scope"]:
            if _has_index(insp, "workspace_user_documents", idx):
                op.drop_index(idx, table_name="workspace_user_documents")
        op.drop_table("workspace_user_documents")

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_addresses"):
        for idx in ["ix_workspace_user_address_scope_primary", "ix_workspace_user_address_scope_public", "ix_workspace_user_address_scope"]:
            if _has_index(insp, "workspace_user_addresses", idx):
                op.drop_index(idx, table_name="workspace_user_addresses")
        op.drop_table("workspace_user_addresses")

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_contact_channels"):
        for idx in ["ix_workspace_user_contact_scope_type", "ix_workspace_user_contact_scope_primary", "ix_workspace_user_contact_scope_public", "ix_workspace_user_contact_scope"]:
            if _has_index(insp, "workspace_user_contact_channels", idx):
                op.drop_index(idx, table_name="workspace_user_contact_channels")
        op.drop_table("workspace_user_contact_channels")

    insp = sa.inspect(bind)
    if _has_table(insp, "workspace_user_profiles"):
        if _has_index(insp, "workspace_user_profiles", "ix_workspace_user_profile_scope_user"):
            op.drop_index("ix_workspace_user_profile_scope_user", table_name="workspace_user_profiles")
        if _has_index(insp, "workspace_user_profiles", "ix_workspace_user_profile_scope"):
            op.drop_index("ix_workspace_user_profile_scope", table_name="workspace_user_profiles")
        if _has_unique(insp, "workspace_user_profiles", "uq_workspace_user_profile_scope_user"):
            op.drop_constraint("uq_workspace_user_profile_scope_user", "workspace_user_profiles", type_="unique")
        op.drop_table("workspace_user_profiles")
