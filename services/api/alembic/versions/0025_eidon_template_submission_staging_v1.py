"""eidon template submission staging v1

Revision ID: 0025_eidon_tpl_stage_v1
Revises: 0024_authz_fast_path_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0025_eidon_tpl_stage_v1"
down_revision = "0024_authz_fast_path_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_template_submission_staging"):
        op.create_table(
            "eidon_template_submission_staging",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("source_capability", sa.String(length=64), nullable=False, server_default="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1"),
            sa.Column("submission_shape_version", sa.String(length=16), nullable=False, server_default="v1"),
            sa.Column("pattern_version", sa.String(length=32), nullable=False, server_default="v1-feedback"),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="STAGED_REVIEW_REQUIRED"),
            sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("quality_score", sa.Integer(), nullable=True),
            sa.Column("authoritative_publish_allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("rollback_from_submission_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("de_identified_pattern_features_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("source_traceability_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("submission_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("raw_tenant_document_included", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("submitted_by", sa.String(length=255), nullable=True),
            sa.Column("reviewed_by", sa.String(length=255), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_tpl_stage_tenant_status_created
        ON eidon_template_submission_staging (tenant_id, status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_tpl_stage_fingerprint_version_created
        ON eidon_template_submission_staging (template_fingerprint, pattern_version, created_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_template_submission_staging"):
        op.drop_index("ix_eidon_tpl_stage_fingerprint_version_created", table_name="eidon_template_submission_staging")
        op.drop_index("ix_eidon_tpl_stage_tenant_status_created", table_name="eidon_template_submission_staging")
        op.drop_table("eidon_template_submission_staging")
