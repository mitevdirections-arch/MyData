"""tenant authz effective permissions fast path

Revision ID: 0024_authz_fast_path_v1
Revises: 0023_authz_ent_db_idx
Create Date: 2026-03-10
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0024_authz_fast_path_v1"
down_revision = "0023_authz_ent_db_idx"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "workspace_user_effective_permissions"):
        op.create_table(
            "workspace_user_effective_permissions",
            sa.Column("workspace_type", sa.String(length=16), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("employment_status", sa.String(length=32), nullable=False, server_default="INACTIVE"),
            sa.Column("effective_permissions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("source_hash_sha256", sa.String(length=64), nullable=True),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("workspace_type", "workspace_id", "user_id", name="pk_workspace_user_effective_permissions"),
        )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_workspace_user_eff_scope
        ON workspace_user_effective_permissions (workspace_type, workspace_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_workspace_user_eff_scope_updated
        ON workspace_user_effective_permissions (workspace_type, workspace_id, updated_at DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "workspace_user_effective_permissions"):
        op.drop_index("ix_workspace_user_eff_scope_updated", table_name="workspace_user_effective_permissions")
        op.drop_index("ix_workspace_user_eff_scope", table_name="workspace_user_effective_permissions")
        op.drop_table("workspace_user_effective_permissions")
