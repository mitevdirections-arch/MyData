"""add license issuance control tables

Revision ID: 0007_license_issuance_control
Revises: 0006_guard_bot_checks
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_license_issuance_control"
down_revision = "0006_guard_bot_checks"
branch_labels = None
depends_on = None


def _has_index(insp, table_name: str, idx: str) -> bool:
    try:
        return any(i.get("name") == idx for i in insp.get_indexes(table_name))
    except Exception:  # noqa: BLE001
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "license_issuance_policies" not in insp.get_table_names():
        op.create_table(
            "license_issuance_policies",
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default=sa.text("'SEMI'")),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    if "license_issue_requests" not in insp.get_table_names():
        op.create_table(
            "license_issue_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("request_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("requested_by", sa.String(length=255), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("approved_by", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_note", sa.String(length=1024), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    insp = sa.inspect(bind)
    if "license_issue_requests" in insp.get_table_names():
        if not _has_index(insp, "license_issue_requests", "ix_license_issue_req_tenant_status"):
            op.create_index("ix_license_issue_req_tenant_status", "license_issue_requests", ["tenant_id", "status", "requested_at"], unique=False)
        if not _has_index(insp, "license_issue_requests", "ix_license_issue_req_status_requested"):
            op.create_index("ix_license_issue_req_status_requested", "license_issue_requests", ["status", "requested_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "license_issue_requests" in insp.get_table_names():
        if _has_index(insp, "license_issue_requests", "ix_license_issue_req_status_requested"):
            op.drop_index("ix_license_issue_req_status_requested", table_name="license_issue_requests")
        if _has_index(insp, "license_issue_requests", "ix_license_issue_req_tenant_status"):
            op.drop_index("ix_license_issue_req_tenant_status", table_name="license_issue_requests")
        op.drop_table("license_issue_requests")

    insp = sa.inspect(bind)
    if "license_issuance_policies" in insp.get_table_names():
        op.drop_table("license_issuance_policies")