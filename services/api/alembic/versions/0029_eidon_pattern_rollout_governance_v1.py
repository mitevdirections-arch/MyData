"""eidon pattern rollout governance v1

Revision ID: 0029_eidon_rollout_gov_v1
Revises: 0028_eidon_pattern_dist_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0029_eidon_rollout_gov_v1"
down_revision = "0028_eidon_pattern_dist_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_pattern_rollout_governance_records"):
        op.create_table(
            "eidon_pattern_rollout_governance_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("distribution_record_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("pattern_version", sa.String(length=32), nullable=False, server_default="v1-feedback"),
            sa.Column("governance_status", sa.String(length=32), nullable=False, server_default="ROLLOUT_GOVERNANCE_RECORDED"),
            sa.Column("eligibility_decision", sa.String(length=32), nullable=False),
            sa.Column("governance_note", sa.String(length=512), nullable=True),
            sa.Column("governance_meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("rollback_from_governance_record_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("recorded_by", sa.String(length=255), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("authoritative_publish_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.CheckConstraint(
                "governance_status = 'ROLLOUT_GOVERNANCE_RECORDED'",
                name="ck_eidon_rollout_governance_status_v1",
            ),
            sa.CheckConstraint(
                "eligibility_decision IN ('ELIGIBLE','NOT_ELIGIBLE')",
                name="ck_eidon_rollout_eligibility_decision_v1",
            ),
            sa.ForeignKeyConstraint(["distribution_record_id"], ["eidon_pattern_distribution_records.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["rollback_from_governance_record_id"],
                ["eidon_pattern_rollout_governance_records.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_eidon_rollout_gov_distribution_unique
        ON eidon_pattern_rollout_governance_records (distribution_record_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_rollout_gov_tenant_recorded
        ON eidon_pattern_rollout_governance_records (tenant_id, recorded_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_rollout_gov_fingerprint_recorded
        ON eidon_pattern_rollout_governance_records (template_fingerprint, recorded_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_pattern_rollout_governance_records"):
        op.drop_index(
            "ix_eidon_rollout_gov_fingerprint_recorded",
            table_name="eidon_pattern_rollout_governance_records",
        )
        op.drop_index(
            "ix_eidon_rollout_gov_tenant_recorded",
            table_name="eidon_pattern_rollout_governance_records",
        )
        op.drop_index(
            "ix_eidon_rollout_gov_distribution_unique",
            table_name="eidon_pattern_rollout_governance_records",
        )
        op.drop_table("eidon_pattern_rollout_governance_records")

