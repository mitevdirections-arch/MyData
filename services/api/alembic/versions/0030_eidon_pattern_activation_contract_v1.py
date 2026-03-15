"""eidon pattern activation contract v1

Revision ID: 0030_eidon_activation_v1
Revises: 0029_eidon_rollout_gov_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0030_eidon_activation_v1"
down_revision = "0029_eidon_rollout_gov_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_pattern_activation_records"):
        op.create_table(
            "eidon_pattern_activation_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("rollout_governance_record_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("pattern_version", sa.String(length=32), nullable=False, server_default="v1-feedback"),
            sa.Column("activation_status", sa.String(length=32), nullable=False, server_default="ACTIVATION_RECORDED"),
            sa.Column("activation_note", sa.String(length=512), nullable=True),
            sa.Column("activation_meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("rollback_from_activation_record_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("recorded_by", sa.String(length=255), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("authoritative_publish_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.CheckConstraint(
                "activation_status = 'ACTIVATION_RECORDED'",
                name="ck_eidon_activation_status_v1",
            ),
            sa.ForeignKeyConstraint(["rollout_governance_record_id"], ["eidon_pattern_rollout_governance_records.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["rollback_from_activation_record_id"],
                ["eidon_pattern_activation_records.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_eidon_activation_rollout_gov_unique
        ON eidon_pattern_activation_records (rollout_governance_record_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_activation_tenant_recorded
        ON eidon_pattern_activation_records (tenant_id, recorded_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_activation_fingerprint_recorded
        ON eidon_pattern_activation_records (template_fingerprint, recorded_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_pattern_activation_records"):
        op.drop_index(
            "ix_eidon_activation_fingerprint_recorded",
            table_name="eidon_pattern_activation_records",
        )
        op.drop_index(
            "ix_eidon_activation_tenant_recorded",
            table_name="eidon_pattern_activation_records",
        )
        op.drop_index(
            "ix_eidon_activation_rollout_gov_unique",
            table_name="eidon_pattern_activation_records",
        )
        op.drop_table("eidon_pattern_activation_records")

