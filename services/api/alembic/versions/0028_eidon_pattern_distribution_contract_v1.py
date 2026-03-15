"""eidon pattern distribution contract v1

Revision ID: 0028_eidon_pattern_dist_v1
Revises: 0027_eidon_ai_quality_events_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0028_eidon_pattern_dist_v1"
down_revision = "0027_eidon_ai_quality_events_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_pattern_distribution_records"):
        op.create_table(
            "eidon_pattern_distribution_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("publish_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("pattern_version", sa.String(length=32), nullable=False, server_default="v1-feedback"),
            sa.Column("distribution_status", sa.String(length=32), nullable=False, server_default="DISTRIBUTION_RECORDED"),
            sa.Column("distribution_note", sa.String(length=512), nullable=True),
            sa.Column("distribution_meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("rollback_from_distribution_record_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("recorded_by", sa.String(length=255), nullable=False),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("authoritative_publish_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.CheckConstraint(
                "distribution_status = 'DISTRIBUTION_RECORDED'",
                name="ck_eidon_pattern_distribution_status_v1",
            ),
            sa.ForeignKeyConstraint(["publish_artifact_id"], ["eidon_pattern_publish_artifacts.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["rollback_from_distribution_record_id"],
                ["eidon_pattern_distribution_records.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_eidon_pattern_distribution_publish_unique
        ON eidon_pattern_distribution_records (publish_artifact_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_pattern_distribution_tenant_recorded
        ON eidon_pattern_distribution_records (tenant_id, recorded_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_pattern_distribution_fingerprint_recorded
        ON eidon_pattern_distribution_records (template_fingerprint, recorded_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_pattern_distribution_records"):
        op.drop_index(
            "ix_eidon_pattern_distribution_fingerprint_recorded",
            table_name="eidon_pattern_distribution_records",
        )
        op.drop_index(
            "ix_eidon_pattern_distribution_tenant_recorded",
            table_name="eidon_pattern_distribution_records",
        )
        op.drop_index(
            "ix_eidon_pattern_distribution_publish_unique",
            table_name="eidon_pattern_distribution_records",
        )
        op.drop_table("eidon_pattern_distribution_records")
