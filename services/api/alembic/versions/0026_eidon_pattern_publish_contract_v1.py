"""eidon pattern publish contract v1

Revision ID: 0026_eidon_pattern_publish_v1
Revises: 0025_eidon_tpl_stage_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0026_eidon_pattern_publish_v1"
down_revision = "0025_eidon_tpl_stage_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_pattern_publish_artifacts"):
        op.create_table(
            "eidon_pattern_publish_artifacts",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("source_submission_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("source_capability", sa.String(length=64), nullable=False, server_default="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"),
            sa.Column("submission_shape_version", sa.String(length=16), nullable=False, server_default="v1"),
            sa.Column("pattern_version", sa.String(length=32), nullable=False, server_default="v1-feedback"),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("quality_score", sa.Integer(), nullable=False),
            sa.Column("de_identified_pattern_features_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("authoritative_publish_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("rollback_capable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("rollback_from_submission_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("rollback_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("publish_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("published_by", sa.String(length=255), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["source_submission_id"], ["eidon_template_submission_staging.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_eidon_publish_source_submission_unique
        ON eidon_pattern_publish_artifacts (source_submission_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_publish_tenant_created
        ON eidon_pattern_publish_artifacts (tenant_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_publish_fingerprint_version_published
        ON eidon_pattern_publish_artifacts (template_fingerprint, pattern_version, published_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_pattern_publish_artifacts"):
        op.drop_index("ix_eidon_publish_fingerprint_version_published", table_name="eidon_pattern_publish_artifacts")
        op.drop_index("ix_eidon_publish_tenant_created", table_name="eidon_pattern_publish_artifacts")
        op.drop_index("ix_eidon_publish_source_submission_unique", table_name="eidon_pattern_publish_artifacts")
        op.drop_table("eidon_pattern_publish_artifacts")
