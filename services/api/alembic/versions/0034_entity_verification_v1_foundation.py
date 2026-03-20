"""entity verification v1 foundation

Revision ID: 0034_entity_verification_v1
Revises: 0033_device_leases_foundation
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0034_entity_verification_v1"
down_revision = "0033_device_leases_foundation"
branch_labels = None
depends_on = None


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    return table_name in insp.get_table_names()


def _has_index(insp: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(idx.get("name") == index_name for idx in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "entity_verification_targets"):
        op.create_table(
            "entity_verification_targets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("subject_type", sa.String(length=32), nullable=False),
            sa.Column("subject_id", sa.String(length=128), nullable=False),
            sa.Column("owner_company_id", sa.String(length=64), nullable=True),
            sa.Column("global_company_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("legal_name", sa.String(length=255), nullable=False),
            sa.Column("normalized_legal_name", sa.String(length=255), nullable=False),
            sa.Column("country_code", sa.String(length=8), nullable=False),
            sa.Column("vat_number", sa.String(length=64), nullable=True),
            sa.Column("vat_number_normalized", sa.String(length=64), nullable=True),
            sa.Column("registration_number", sa.String(length=64), nullable=True),
            sa.Column("registration_number_normalized", sa.String(length=64), nullable=True),
            sa.Column("address_line", sa.String(length=255), nullable=True),
            sa.Column("postal_code", sa.String(length=32), nullable=True),
            sa.Column("city", sa.String(length=128), nullable=True),
            sa.Column("website_url", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("subject_type IN ('TENANT', 'PARTNER', 'EXTERNAL')", name="ck_entity_verification_target_subject_type"),
            sa.ForeignKeyConstraint(["owner_company_id"], ["tenants.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["global_company_id"], ["global_companies.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("subject_type", "subject_id", name="uq_entity_verification_target_subject"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_targets"):
        if not _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_owner_subject"):
            op.create_index("ix_entity_verification_target_owner_subject", "entity_verification_targets", ["owner_company_id", "subject_type"], unique=False)
        if not _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_global_company"):
            op.create_index("ix_entity_verification_target_global_company", "entity_verification_targets", ["global_company_id"], unique=False)
        if not _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_vat"):
            op.create_index("ix_entity_verification_target_country_vat", "entity_verification_targets", ["country_code", "vat_number_normalized"], unique=False)
        if not _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_registration"):
            op.create_index(
                "ix_entity_verification_target_country_registration",
                "entity_verification_targets",
                ["country_code", "registration_number_normalized"],
                unique=False,
            )
        if not _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_name"):
            op.create_index("ix_entity_verification_target_country_name", "entity_verification_targets", ["country_code", "normalized_legal_name"], unique=False)

    insp = sa.inspect(bind)
    if not _has_table(insp, "entity_verification_checks"):
        op.create_table(
            "entity_verification_checks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider_code", sa.String(length=64), nullable=False),
            sa.Column("check_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=True),
            sa.Column("provider_reference", sa.String(length=255), nullable=True),
            sa.Column("provider_message_code", sa.String(length=128), nullable=True),
            sa.Column("provider_message_text", sa.String(length=1024), nullable=True),
            sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.String(length=255), nullable=True),
            sa.CheckConstraint(
                "status IN ('VERIFIED', 'NOT_VERIFIED', 'UNAVAILABLE', 'NOT_APPLICABLE', 'PARTIAL_MATCH')",
                name="ck_entity_verification_check_status",
            ),
            sa.ForeignKeyConstraint(["target_id"], ["entity_verification_targets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_checks"):
        if not _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_target_provider_checked"):
            op.create_index(
                "ix_entity_verification_checks_target_provider_checked",
                "entity_verification_checks",
                ["target_id", "provider_code", "checked_at"],
                unique=False,
            )
        if not _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_target_checked"):
            op.create_index("ix_entity_verification_checks_target_checked", "entity_verification_checks", ["target_id", "checked_at"], unique=False)
        if not _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_provider_status_checked"):
            op.create_index(
                "ix_entity_verification_checks_provider_status_checked",
                "entity_verification_checks",
                ["provider_code", "status", "checked_at"],
                unique=False,
            )

    insp = sa.inspect(bind)
    if not _has_table(insp, "entity_verification_summary"):
        op.create_table(
            "entity_verification_summary",
            sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("overall_status", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_recommended_check_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_provider_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("warning_provider_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unavailable_provider_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("overall_confidence", sa.Float(), nullable=True),
            sa.Column("badges_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("overall_status IN ('GOOD', 'WARNING', 'PENDING', 'UNKNOWN')", name="ck_entity_verification_summary_status"),
            sa.ForeignKeyConstraint(["target_id"], ["entity_verification_targets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("target_id"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_summary") and not _has_index(insp, "entity_verification_summary", "ix_entity_verification_summary_status_checked"):
        op.create_index("ix_entity_verification_summary_status_checked", "entity_verification_summary", ["overall_status", "last_checked_at"], unique=False)

    insp = sa.inspect(bind)
    if not _has_table(insp, "entity_verification_inflight"):
        op.create_table(
            "entity_verification_inflight",
            sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider_code", sa.String(length=64), nullable=False),
            sa.Column("lease_started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("request_id", sa.String(length=128), nullable=True),
            sa.ForeignKeyConstraint(["target_id"], ["entity_verification_targets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("target_id", "provider_code"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_inflight") and not _has_index(insp, "entity_verification_inflight", "ix_entity_verification_inflight_lease_expires"):
        op.create_index("ix_entity_verification_inflight_lease_expires", "entity_verification_inflight", ["lease_expires_at"], unique=False)

    insp = sa.inspect(bind)
    if not _has_table(insp, "entity_verification_provider_state"):
        op.create_table(
            "entity_verification_provider_state",
            sa.Column("provider_code", sa.String(length=64), nullable=False),
            sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("provider_code"),
        )

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_provider_state") and not _has_index(insp, "entity_verification_provider_state", "ix_entity_verification_provider_state_cooldown"):
        op.create_index("ix_entity_verification_provider_state_cooldown", "entity_verification_provider_state", ["cooldown_until"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "entity_verification_provider_state"):
        if _has_index(insp, "entity_verification_provider_state", "ix_entity_verification_provider_state_cooldown"):
            op.drop_index("ix_entity_verification_provider_state_cooldown", table_name="entity_verification_provider_state")
        op.drop_table("entity_verification_provider_state")

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_inflight"):
        if _has_index(insp, "entity_verification_inflight", "ix_entity_verification_inflight_lease_expires"):
            op.drop_index("ix_entity_verification_inflight_lease_expires", table_name="entity_verification_inflight")
        op.drop_table("entity_verification_inflight")

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_summary"):
        if _has_index(insp, "entity_verification_summary", "ix_entity_verification_summary_status_checked"):
            op.drop_index("ix_entity_verification_summary_status_checked", table_name="entity_verification_summary")
        op.drop_table("entity_verification_summary")

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_checks"):
        if _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_provider_status_checked"):
            op.drop_index("ix_entity_verification_checks_provider_status_checked", table_name="entity_verification_checks")
        if _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_target_checked"):
            op.drop_index("ix_entity_verification_checks_target_checked", table_name="entity_verification_checks")
        if _has_index(insp, "entity_verification_checks", "ix_entity_verification_checks_target_provider_checked"):
            op.drop_index("ix_entity_verification_checks_target_provider_checked", table_name="entity_verification_checks")
        op.drop_table("entity_verification_checks")

    insp = sa.inspect(bind)
    if _has_table(insp, "entity_verification_targets"):
        if _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_name"):
            op.drop_index("ix_entity_verification_target_country_name", table_name="entity_verification_targets")
        if _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_registration"):
            op.drop_index("ix_entity_verification_target_country_registration", table_name="entity_verification_targets")
        if _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_country_vat"):
            op.drop_index("ix_entity_verification_target_country_vat", table_name="entity_verification_targets")
        if _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_global_company"):
            op.drop_index("ix_entity_verification_target_global_company", table_name="entity_verification_targets")
        if _has_index(insp, "entity_verification_targets", "ix_entity_verification_target_owner_subject"):
            op.drop_index("ix_entity_verification_target_owner_subject", table_name="entity_verification_targets")
        op.drop_table("entity_verification_targets")
