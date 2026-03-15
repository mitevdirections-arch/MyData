"""add profile and i18n foundation tables

Revision ID: 0010_profile_i18n_foundation
Revises: 0009_guard_bot_lockout_policy
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_profile_i18n_foundation"
down_revision = "0009_guard_bot_lockout_policy"
branch_labels = None
depends_on = None


def _has_index(insp, table_name: str, idx: str) -> bool:
    try:
        return any(i.get("name") == idx for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "admin_profiles" not in insp.get_table_names():
        op.create_table(
            "admin_profiles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=True),
            sa.Column("avatar_url", sa.String(length=1024), nullable=True),
            sa.Column("preferred_locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("preferred_time_zone", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
            sa.Column("date_style", sa.String(length=8), nullable=False, server_default=sa.text("'YMD'")),
            sa.Column("time_style", sa.String(length=8), nullable=False, server_default=sa.text("'H24'")),
            sa.Column("unit_system", sa.String(length=16), nullable=False, server_default=sa.text("'metric'")),
            sa.Column("notification_prefs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_admin_profile_workspace_user"),
        )

    if "workspace_organization_profiles" not in insp.get_table_names():
        op.create_table(
            "workspace_organization_profiles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("legal_name", sa.String(length=255), nullable=True),
            sa.Column("vat_number", sa.String(length=64), nullable=True),
            sa.Column("registration_number", sa.String(length=64), nullable=True),
            sa.Column("company_size_hint", sa.String(length=64), nullable=True),
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
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", name="uq_workspace_org_profile_scope"),
        )

    if "workspace_roles" not in insp.get_table_names():
        op.create_table(
            "workspace_roles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("role_code", sa.String(length=64), nullable=False),
            sa.Column("role_name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.String(length=1024), nullable=True),
            sa.Column("permissions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", "role_code", name="uq_workspace_role_scope_code"),
        )

    if "workspace_users" not in insp.get_table_names():
        op.create_table(
            "workspace_users",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=True),
            sa.Column("department", sa.String(length=128), nullable=True),
            sa.Column("employment_status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("direct_permissions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", "user_id", name="uq_workspace_user_scope_user"),
        )

    if "workspace_user_roles" not in insp.get_table_names():
        op.create_table(
            "workspace_user_roles",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("role_code", sa.String(length=64), nullable=False),
            sa.Column("assigned_by", sa.String(length=255), nullable=True),
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", "user_id", "role_code", name="uq_workspace_user_role_scope"),
        )

    if "i18n_workspace_policies" not in insp.get_table_names():
        op.create_table(
            "i18n_workspace_policies",
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("default_locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("fallback_locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("enabled_locales_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[\"en\"]'::jsonb")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("workspace_type", "workspace_id"),
        )

    insp = sa.inspect(bind)

    if "admin_profiles" in insp.get_table_names():
        if not _has_index(insp, "admin_profiles", "ix_admin_profile_workspace"):
            op.create_index("ix_admin_profile_workspace", "admin_profiles", ["workspace_type", "workspace_id"], unique=False)

    if "workspace_organization_profiles" in insp.get_table_names():
        if not _has_index(insp, "workspace_organization_profiles", "ix_workspace_org_profile_scope"):
            op.create_index("ix_workspace_org_profile_scope", "workspace_organization_profiles", ["workspace_type", "workspace_id"], unique=False)

    if "workspace_roles" in insp.get_table_names():
        if not _has_index(insp, "workspace_roles", "ix_workspace_role_scope"):
            op.create_index("ix_workspace_role_scope", "workspace_roles", ["workspace_type", "workspace_id"], unique=False)

    if "workspace_users" in insp.get_table_names():
        if not _has_index(insp, "workspace_users", "ix_workspace_user_scope"):
            op.create_index("ix_workspace_user_scope", "workspace_users", ["workspace_type", "workspace_id"], unique=False)

    if "workspace_user_roles" in insp.get_table_names():
        if not _has_index(insp, "workspace_user_roles", "ix_workspace_user_role_scope_user"):
            op.create_index("ix_workspace_user_role_scope_user", "workspace_user_roles", ["workspace_type", "workspace_id", "user_id"], unique=False)

    if "i18n_workspace_policies" in insp.get_table_names():
        if not _has_index(insp, "i18n_workspace_policies", "ix_i18n_workspace_scope"):
            op.create_index("ix_i18n_workspace_scope", "i18n_workspace_policies", ["workspace_type", "workspace_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "i18n_workspace_policies" in insp.get_table_names():
        if _has_index(insp, "i18n_workspace_policies", "ix_i18n_workspace_scope"):
            op.drop_index("ix_i18n_workspace_scope", table_name="i18n_workspace_policies")
        op.drop_table("i18n_workspace_policies")

    insp = sa.inspect(bind)
    if "workspace_user_roles" in insp.get_table_names():
        if _has_index(insp, "workspace_user_roles", "ix_workspace_user_role_scope_user"):
            op.drop_index("ix_workspace_user_role_scope_user", table_name="workspace_user_roles")
        op.drop_table("workspace_user_roles")

    insp = sa.inspect(bind)
    if "workspace_users" in insp.get_table_names():
        if _has_index(insp, "workspace_users", "ix_workspace_user_scope"):
            op.drop_index("ix_workspace_user_scope", table_name="workspace_users")
        op.drop_table("workspace_users")

    insp = sa.inspect(bind)
    if "workspace_roles" in insp.get_table_names():
        if _has_index(insp, "workspace_roles", "ix_workspace_role_scope"):
            op.drop_index("ix_workspace_role_scope", table_name="workspace_roles")
        op.drop_table("workspace_roles")

    insp = sa.inspect(bind)
    if "workspace_organization_profiles" in insp.get_table_names():
        if _has_index(insp, "workspace_organization_profiles", "ix_workspace_org_profile_scope"):
            op.drop_index("ix_workspace_org_profile_scope", table_name="workspace_organization_profiles")
        op.drop_table("workspace_organization_profiles")

    insp = sa.inspect(bind)
    if "admin_profiles" in insp.get_table_names():
        if _has_index(insp, "admin_profiles", "ix_admin_profile_workspace"):
            op.drop_index("ix_admin_profile_workspace", table_name="admin_profiles")
        op.drop_table("admin_profiles")
