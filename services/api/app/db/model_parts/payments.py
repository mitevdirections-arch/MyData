from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TenantCreditAccount(Base):
    __tablename__ = "tenant_credit_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_credit_account_tenant"),
        Index("ix_credit_account_mode_status", "payment_mode", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    payment_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="PREPAID")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    credit_limit_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")

    terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    auto_hold_on_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    overdue_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PaymentInvoiceSequence(Base):
    __tablename__ = "payment_invoice_sequences"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_payment_invoice_seq_tenant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    next_serial: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"
    __table_args__ = (
        Index("ix_payment_invoice_tenant_status_due", "tenant_id", "status", "due_at"),
        Index("ix_payment_invoice_source", "source_type", "source_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_no: Mapped[str] = mapped_column(String(64), nullable=False)
    template_code: Mapped[str] = mapped_column(String(32), nullable=False, default="EU_VAT_V1")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ISSUED")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    issue_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    compliance_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "TenantCreditAccount",
    "PaymentInvoiceSequence",
    "PaymentInvoice",
]
