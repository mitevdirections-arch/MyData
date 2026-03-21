"""merge main + device-policy alembic heads

Revision ID: 0037_alembic_graph_harmonization
Revises: 0035_workspace_user_primary_invariant, 0036_device_policy_v1_hardening
Create Date: 2026-03-22
"""

from __future__ import annotations


revision = "0037_alembic_graph_harmonization"
down_revision = ("0035_workspace_user_primary_invariant", "0036_device_policy_v1_hardening")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Graph-harmonization merge revision only: no schema changes.
    return None


def downgrade() -> None:
    # No-op by design.
    return None
