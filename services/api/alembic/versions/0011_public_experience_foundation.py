"""add public experience foundation tables

Revision ID: 0011_public_experience
Revises: 0010_profile_i18n_foundation
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_public_experience"
down_revision = "0010_profile_i18n_foundation"
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

    if "public_workspace_settings" not in insp.get_table_names():
        op.create_table(
            "public_workspace_settings",
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("show_company_info", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("show_fleet", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("show_contacts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("show_price_list", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("show_working_hours", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("workspace_type", "workspace_id"),
        )

    if "public_brand_assets" not in insp.get_table_names():
        op.create_table(
            "public_brand_assets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("asset_kind", sa.String(length=32), nullable=False, server_default=sa.text("'LOGO'")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING_UPLOAD'")),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("sha256", sa.String(length=128), nullable=True),
            sa.Column("storage_provider", sa.String(length=32), nullable=False, server_default=sa.text("'minio'")),
            sa.Column("bucket", sa.String(length=128), nullable=False),
            sa.Column("object_key", sa.String(length=512), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    if "public_page_drafts" not in insp.get_table_names():
        op.create_table(
            "public_page_drafts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("page_code", sa.String(length=32), nullable=False, server_default=sa.text("'HOME'")),
            sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_type", "workspace_id", "locale", "page_code", name="uq_public_page_draft_scope"),
        )

    if "public_page_published" not in insp.get_table_names():
        op.create_table(
            "public_page_published",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("page_code", sa.String(length=32), nullable=False, server_default=sa.text("'HOME'")),
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("publish_note", sa.String(length=1024), nullable=True),
            sa.Column("published_by", sa.String(length=255), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "public_brand_assets" in insp.get_table_names() and not _has_index(insp, "public_brand_assets", "ix_public_brand_asset_scope_kind_status"):
        op.create_index("ix_public_brand_asset_scope_kind_status", "public_brand_assets", ["workspace_type", "workspace_id", "asset_kind", "status"], unique=False)

    if "public_page_drafts" in insp.get_table_names() and not _has_index(insp, "public_page_drafts", "ix_public_page_draft_scope"):
        op.create_index("ix_public_page_draft_scope", "public_page_drafts", ["workspace_type", "workspace_id", "locale", "page_code"], unique=False)

    if "public_page_published" in insp.get_table_names() and not _has_index(insp, "public_page_published", "ix_public_page_published_scope"):
        op.create_index("ix_public_page_published_scope", "public_page_published", ["workspace_type", "workspace_id", "locale", "page_code", "version"], unique=False)

    # Data bridge from legacy tenant-only settings table if present.
    insp = sa.inspect(bind)
    if "public_workspace_settings" in insp.get_table_names() and "public_profile_settings" in insp.get_table_names():
        op.execute(
            """
            INSERT INTO public_workspace_settings (
                workspace_type,
                workspace_id,
                show_company_info,
                show_fleet,
                show_contacts,
                show_price_list,
                show_working_hours,
                updated_by,
                updated_at
            )
            SELECT
                'TENANT' AS workspace_type,
                tenant_id AS workspace_id,
                show_company_info,
                show_fleet,
                show_contacts,
                show_price_list,
                show_working_hours,
                updated_by,
                updated_at
            FROM public_profile_settings
            ON CONFLICT (workspace_type, workspace_id) DO NOTHING
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "public_page_published" in insp.get_table_names():
        if _has_index(insp, "public_page_published", "ix_public_page_published_scope"):
            op.drop_index("ix_public_page_published_scope", table_name="public_page_published")
        op.drop_table("public_page_published")

    insp = sa.inspect(bind)
    if "public_page_drafts" in insp.get_table_names():
        if _has_index(insp, "public_page_drafts", "ix_public_page_draft_scope"):
            op.drop_index("ix_public_page_draft_scope", table_name="public_page_drafts")
        op.drop_table("public_page_drafts")

    insp = sa.inspect(bind)
    if "public_brand_assets" in insp.get_table_names():
        if _has_index(insp, "public_brand_assets", "ix_public_brand_asset_scope_kind_status"):
            op.drop_index("ix_public_brand_asset_scope_kind_status", table_name="public_brand_assets")
        op.drop_table("public_brand_assets")

    insp = sa.inspect(bind)
    if "public_workspace_settings" in insp.get_table_names():
        op.drop_table("public_workspace_settings")