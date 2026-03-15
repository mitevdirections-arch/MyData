"""authz and entitlement db path covering indexes

Revision ID: 0023_authz_ent_db_idx
Revises: 0022_orders_perf_indexes
Create Date: 2026-03-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023_authz_ent_db_idx"
down_revision = "0022_orders_perf_indexes"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "workspace_roles"):
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_workspace_role_scope_code_cover
            ON workspace_roles (workspace_type, workspace_id, role_code)
            STORING (permissions_json)
            """
        )

    if _has_table(insp, "workspace_users"):
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_workspace_user_scope_user_cover
            ON workspace_users (workspace_type, workspace_id, user_id)
            STORING (employment_status, direct_permissions_json)
            """
        )

    if _has_table(insp, "licenses"):
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_licenses_tenant_type_status_validto_cover
            ON licenses (tenant_id, license_type, status, valid_to DESC)
            STORING (valid_from)
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_licenses_tenant_module_status_validto_cover
            ON licenses (tenant_id, module_code, status, valid_to DESC)
            STORING (license_type, valid_from)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "licenses"):
        op.drop_index("ix_licenses_tenant_module_status_validto_cover", table_name="licenses")
        op.drop_index("ix_licenses_tenant_type_status_validto_cover", table_name="licenses")

    if _has_table(insp, "workspace_users"):
        op.drop_index("ix_workspace_user_scope_user_cover", table_name="workspace_users")

    if _has_table(insp, "workspace_roles"):
        op.drop_index("ix_workspace_role_scope_code_cover", table_name="workspace_roles")
