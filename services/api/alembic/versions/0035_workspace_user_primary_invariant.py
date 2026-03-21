"""workspace user primary invariant hardening

Revision ID: 0035_workspace_user_primary_invariant
Revises: 0034_entity_verification_v1
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_workspace_user_primary_invariant"
down_revision = "0034_entity_verification_v1"
branch_labels = None
depends_on = None


PRIMARY_INDEXES: tuple[tuple[str, str], ...] = (
    ("workspace_user_contact_channels", "uq_ws_user_contact_primary_true"),
    ("workspace_user_addresses", "uq_ws_user_address_primary_true"),
    ("workspace_user_next_of_kin", "uq_ws_user_nok_primary_true"),
)


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(idx.get("name") == index_name for idx in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _normalize_primary_scope_rows(table_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY workspace_type, workspace_id, user_id
                        ORDER BY
                            CASE WHEN COALESCE(is_primary, false) THEN 0 ELSE 1 END,
                            COALESCE(sort_order, 0) ASC,
                            created_at ASC,
                            id ASC
                    ) AS rn
                FROM {table_name}
            )
            UPDATE {table_name} AS target
            SET is_primary = CASE WHEN ranked.rn = 1 THEN true ELSE false END
            FROM ranked
            WHERE target.id = ranked.id
              AND target.is_primary IS DISTINCT FROM CASE WHEN ranked.rn = 1 THEN true ELSE false END
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table_name, index_name in PRIMARY_INDEXES:
        if not _has_table(insp, table_name):
            continue
        _normalize_primary_scope_rows(table_name)
        insp = sa.inspect(bind)
        if not _has_index(insp, table_name, index_name):
            op.create_index(
                index_name,
                table_name,
                ["workspace_type", "workspace_id", "user_id"],
                unique=True,
                postgresql_where=sa.text("is_primary"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table_name, index_name in PRIMARY_INDEXES:
        if not _has_table(insp, table_name):
            continue
        if _has_index(insp, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
