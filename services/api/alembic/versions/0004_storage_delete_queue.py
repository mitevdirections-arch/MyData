"""add storage delete retry queue

Revision ID: 0004_storage_delete_queue
Revises: 0003_storage_grants
Create Date: 2026-03-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_storage_delete_queue"
down_revision = "0003_storage_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_delete_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("object_meta_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False, server_default=sa.text("'retention'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("8")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_delete_queue_status_next", "storage_delete_queue", ["status", "next_attempt_at"], unique=False)
    op.create_index("ix_storage_delete_queue_tenant_status", "storage_delete_queue", ["tenant_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_storage_delete_queue_tenant_status", table_name="storage_delete_queue")
    op.drop_index("ix_storage_delete_queue_status_next", table_name="storage_delete_queue")
    op.drop_table("storage_delete_queue")