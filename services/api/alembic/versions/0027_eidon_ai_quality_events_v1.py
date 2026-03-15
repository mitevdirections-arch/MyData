"""eidon ai quality events v1

Revision ID: 0027_eidon_ai_quality_events_v1
Revises: 0026_eidon_pattern_publish_v1
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0027_eidon_ai_quality_events_v1"
down_revision = "0026_eidon_pattern_publish_v1"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "eidon_ai_quality_events"):
        op.create_table(
            "eidon_ai_quality_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False, server_default="ORDER_INTAKE_FEEDBACK_V1"),
            sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("corrected_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("unresolved_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("human_confirmation_recorded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "confidence_adjustments_summary_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_ai_quality_events_tenant_created
        ON eidon_ai_quality_events (tenant_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_ai_quality_events_type_created
        ON eidon_ai_quality_events (event_type, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_eidon_ai_quality_events_fingerprint_created
        ON eidon_ai_quality_events (template_fingerprint, created_at)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "eidon_ai_quality_events"):
        op.drop_index("ix_eidon_ai_quality_events_fingerprint_created", table_name="eidon_ai_quality_events")
        op.drop_index("ix_eidon_ai_quality_events_type_created", table_name="eidon_ai_quality_events")
        op.drop_index("ix_eidon_ai_quality_events_tenant_created", table_name="eidon_ai_quality_events")
        op.drop_table("eidon_ai_quality_events")
