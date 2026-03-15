"""add guard bot credential and nonce tables

Revision ID: 0008_guard_bot_crypto_controls
Revises: 0007_license_issuance_control
Create Date: 2026-03-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_guard_bot_crypto_controls"
down_revision = "0007_license_issuance_control"
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

    if "guard_bot_credentials" not in insp.get_table_names():
        op.create_table(
            "guard_bot_credentials",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("bot_id", sa.String(length=128), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=True),
            sa.Column("key_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'ACTIVE'")),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.String(length=255), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "bot_id", name="uq_guard_bot_credential_tenant_bot"),
        )

    if "guard_bot_nonces" not in insp.get_table_names():
        op.create_table(
            "guard_bot_nonces",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("bot_id", sa.String(length=128), nullable=False),
            sa.Column("nonce", sa.String(length=128), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("bot_id", "nonce", name="uq_guard_bot_nonce_bot_nonce"),
        )

    insp = sa.inspect(bind)
    if "guard_bot_credentials" in insp.get_table_names():
        if not _has_index(insp, "guard_bot_credentials", "ix_guard_bot_credential_tenant_status"):
            op.create_index("ix_guard_bot_credential_tenant_status", "guard_bot_credentials", ["tenant_id", "status"], unique=False)

    if "guard_bot_nonces" in insp.get_table_names():
        if not _has_index(insp, "guard_bot_nonces", "ix_guard_bot_nonce_expires"):
            op.create_index("ix_guard_bot_nonce_expires", "guard_bot_nonces", ["expires_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "guard_bot_nonces" in insp.get_table_names():
        if _has_index(insp, "guard_bot_nonces", "ix_guard_bot_nonce_expires"):
            op.drop_index("ix_guard_bot_nonce_expires", table_name="guard_bot_nonces")
        op.drop_table("guard_bot_nonces")

    insp = sa.inspect(bind)
    if "guard_bot_credentials" in insp.get_table_names():
        if _has_index(insp, "guard_bot_credentials", "ix_guard_bot_credential_tenant_status"):
            op.drop_index("ix_guard_bot_credential_tenant_status", table_name="guard_bot_credentials")
        op.drop_table("guard_bot_credentials")