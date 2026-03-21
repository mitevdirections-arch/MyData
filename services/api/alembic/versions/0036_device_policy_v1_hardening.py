"""device policy v1 hardening

Revision ID: 0036_device_policy_v1_hardening
Revises: 0035_device_policy_v1
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_device_policy_v1_hardening"
down_revision = "0035_device_policy_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(str(idx.get("name")) == index_name for idx in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def _has_check(insp: sa.Inspector, table_name: str, check_name: str) -> bool:
    try:
        return any(str(ck.get("name")) == check_name for ck in insp.get_check_constraints(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "device_leases"):
        raise RuntimeError("device_leases_table_missing_before_0036")

    # Normalize unknown/legacy state values first.
    op.execute(
        sa.text(
            """
            UPDATE device_leases
            SET state = CASE
                WHEN state IS NULL OR btrim(state) = '' THEN CASE WHEN is_active THEN 'ACTIVE' ELSE 'LOGGED_OUT' END
                WHEN upper(state) IN ('ACTIVE', 'PAUSED', 'BACKGROUND_REACHABLE', 'LOGGED_OUT', 'REVOKED') THEN upper(state)
                ELSE CASE WHEN is_active THEN 'ACTIVE' ELSE 'LOGGED_OUT' END
            END
            """
        )
    )

    # Transitional dual-truth alignment.
    op.execute(sa.text("UPDATE device_leases SET is_active = (state = 'ACTIVE')"))

    # If legacy rows still produce >1 ACTIVE for the same user, keep one canonical ACTIVE row.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    tenant_id,
                    user_id,
                    lower(coalesce(device_class, 'desktop')) AS device_class_norm,
                    row_number() OVER (
                        PARTITION BY tenant_id, user_id
                        ORDER BY coalesce(last_live_at, last_seen_at, state_changed_at, leased_at, now()) DESC, leased_at DESC, id DESC
                    ) AS rn
                FROM device_leases
                WHERE state = 'ACTIVE'
            )
            UPDATE device_leases AS d
            SET
                state = CASE
                    WHEN r.rn = 1 THEN 'ACTIVE'
                    WHEN r.device_class_norm = 'mobile' THEN 'BACKGROUND_REACHABLE'
                    ELSE 'PAUSED'
                END,
                is_active = CASE WHEN r.rn = 1 THEN true ELSE false END,
                state_changed_at = coalesce(d.state_changed_at, now()),
                paused_at = CASE
                    WHEN r.rn <> 1 AND r.device_class_norm <> 'mobile' THEN coalesce(d.paused_at, now())
                    ELSE d.paused_at
                END,
                background_reachable_at = CASE
                    WHEN r.rn <> 1 AND r.device_class_norm = 'mobile' THEN coalesce(d.background_reachable_at, now())
                    ELSE d.background_reachable_at
                END
            FROM ranked AS r
            WHERE d.id = r.id
            """
        )
    )

    # Keep required timing fields non-null after normalization.
    op.execute(
        sa.text(
            """
            UPDATE device_leases
            SET
                state_changed_at = coalesce(state_changed_at, now()),
                last_live_at = coalesce(last_live_at, last_seen_at, leased_at, now()),
                is_active = (state = 'ACTIVE')
            """
        )
    )

    insp = sa.inspect(bind)
    if not _has_check(insp, "device_leases", "ck_device_lease_state_active_consistent"):
        op.create_check_constraint(
            "ck_device_lease_state_active_consistent",
            "device_leases",
            "(state = 'ACTIVE' AND is_active = true) OR (state <> 'ACTIVE' AND is_active = false)",
        )

    insp = sa.inspect(bind)
    if not _has_index(insp, "device_leases", "uq_device_lease_one_active_user"):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_lease_one_active_user "
                "ON device_leases (tenant_id, user_id) WHERE state = 'ACTIVE'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "device_leases"):
        return

    if _has_index(insp, "device_leases", "uq_device_lease_one_active_user"):
        op.drop_index("uq_device_lease_one_active_user", table_name="device_leases")

    insp = sa.inspect(bind)
    if _has_check(insp, "device_leases", "ck_device_lease_state_active_consistent"):
        op.drop_constraint("ck_device_lease_state_active_consistent", "device_leases", type_="check")
