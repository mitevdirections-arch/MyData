"""add support chat and faq tables

Revision ID: 0013_support_channels
Revises: 0012_support_foundation
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_support_channels"
down_revision = "0012_support_foundation"
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

    if "support_messages" not in insp.get_table_names():
        op.create_table(
            "support_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("support_sessions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("channel", sa.String(length=32), nullable=False, server_default=sa.text("'CHAT_HUMAN'")),
            sa.Column("sender_type", sa.String(length=32), nullable=False),
            sa.Column("sender_id", sa.String(length=255), nullable=False),
            sa.Column("body", sa.String(length=8000), nullable=False),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    if "support_faq_entries" not in insp.get_table_names():
        op.create_table(
            "support_faq_entries",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("locale", sa.String(length=32), nullable=False, server_default=sa.text("'en'")),
            sa.Column("category", sa.String(length=64), nullable=False, server_default=sa.text("'GENERAL'")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PUBLISHED'")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("100")),
            sa.Column("question", sa.String(length=512), nullable=False),
            sa.Column("answer", sa.String(length=8000), nullable=False),
            sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "support_messages" in insp.get_table_names() and not _has_index(insp, "support_messages", "ix_support_messages_request_created"):
        op.create_index("ix_support_messages_request_created", "support_messages", ["request_id", "created_at"], unique=False)
    if "support_messages" in insp.get_table_names() and not _has_index(insp, "support_messages", "ix_support_messages_tenant_created"):
        op.create_index("ix_support_messages_tenant_created", "support_messages", ["tenant_id", "created_at"], unique=False)

    if "support_faq_entries" in insp.get_table_names() and not _has_index(insp, "support_faq_entries", "ix_support_faq_locale_status_sort"):
        op.create_index("ix_support_faq_locale_status_sort", "support_faq_entries", ["locale", "status", "sort_order"], unique=False)
    if "support_faq_entries" in insp.get_table_names() and not _has_index(insp, "support_faq_entries", "ix_support_faq_status_updated"):
        op.create_index("ix_support_faq_status_updated", "support_faq_entries", ["status", "updated_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "support_faq_entries" in insp.get_table_names():
        if _has_index(insp, "support_faq_entries", "ix_support_faq_status_updated"):
            op.drop_index("ix_support_faq_status_updated", table_name="support_faq_entries")
        if _has_index(insp, "support_faq_entries", "ix_support_faq_locale_status_sort"):
            op.drop_index("ix_support_faq_locale_status_sort", table_name="support_faq_entries")
        op.drop_table("support_faq_entries")

    insp = sa.inspect(bind)
    if "support_messages" in insp.get_table_names():
        if _has_index(insp, "support_messages", "ix_support_messages_tenant_created"):
            op.drop_index("ix_support_messages_tenant_created", table_name="support_messages")
        if _has_index(insp, "support_messages", "ix_support_messages_request_created"):
            op.drop_index("ix_support_messages_request_created", table_name="support_messages")
        op.drop_table("support_messages")