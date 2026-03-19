from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class GlobalCompany(Base):
    __tablename__ = "global_companies"
    __table_args__ = (
        Index("ix_global_companies_country_vat", "country_code", "vat_number"),
        Index("ix_global_companies_country_registration", "country_code", "registration_number"),
        Index("ix_global_companies_country_normalized_name", "country_code", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    main_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    main_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class GlobalCompanyReputation(Base):
    __tablename__ = "global_company_reputation"

    global_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("global_companies.id", ondelete="CASCADE"), primary_key=True)
    total_tenants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_completed_orders_rated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_execution_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_communication_docs: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_payment_discipline: Mapped[float | None] = mapped_column(Float, nullable=True)
    global_overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_payment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_quality_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blacklist_signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class TenantPartner(Base):
    __tablename__ = "tenant_partners"
    __table_args__ = (
        UniqueConstraint("company_id", "partner_code", name="uq_tenant_partner_company_code"),
        Index("ix_tenant_partners_company_status_updated", "company_id", "status", "updated_at"),
        Index("ix_tenant_partners_company_global", "company_id", "global_company_id"),
        Index("ix_tenant_partners_company_vat", "company_id", "country_code", "vat_number"),
        Index("ix_tenant_partners_company_registration", "company_id", "country_code", "registration_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    # Owner tenant/company identity in MyData scope (not a global company reference).
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    global_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("global_companies.id", ondelete="SET NULL"), nullable=True)

    partner_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    main_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    main_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")

    is_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_watchlisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blacklist_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    internal_note: Mapped[str | None] = mapped_column(String(4000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantPartnerRole(Base):
    __tablename__ = "tenant_partner_roles"
    __table_args__ = (
        UniqueConstraint("partner_id", "role_code", name="uq_tenant_partner_role"),
        Index("ix_tenant_partner_roles_partner", "partner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)


class TenantPartnerAddress(Base):
    __tablename__ = "tenant_partner_addresses"
    __table_args__ = (
        Index("ix_tenant_partner_addresses_company_partner", "company_id", "partner_id"),
        Index("ix_tenant_partner_addresses_partner_primary", "partner_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)

    address_type: Mapped[str] = mapped_column(String(32), nullable=False, default="HQ")
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantPartnerBankAccount(Base):
    __tablename__ = "tenant_partner_bank_accounts"
    __table_args__ = (
        Index("ix_tenant_partner_bank_company_partner", "company_id", "partner_id"),
        Index("ix_tenant_partner_bank_partner_primary", "partner_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)

    account_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    swift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantPartnerContact(Base):
    __tablename__ = "tenant_partner_contacts"
    __table_args__ = (
        Index("ix_tenant_partner_contacts_company_partner", "company_id", "partner_id"),
        Index("ix_tenant_partner_contacts_partner_primary", "partner_id", "is_primary"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)

    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantPartnerDocument(Base):
    __tablename__ = "tenant_partner_documents"
    __table_args__ = (
        Index("ix_tenant_partner_documents_company_partner", "company_id", "partner_id"),
        Index("ix_tenant_partner_documents_partner_doc_type", "partner_id", "doc_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PartnerOrderRating(Base):
    __tablename__ = "partner_order_ratings"
    __table_args__ = (
        Index("ix_partner_order_ratings_company_partner_created", "company_id", "partner_id", "created_at"),
        Index("ix_partner_order_ratings_company_order", "company_id", "order_id"),
        CheckConstraint("execution_quality_stars BETWEEN 1 AND 6", name="ck_partner_rating_execution_stars"),
        CheckConstraint("communication_docs_stars BETWEEN 1 AND 6", name="ck_partner_rating_communication_stars"),
        CheckConstraint(
            "(payment_discipline_stars IS NULL) OR (payment_discipline_stars BETWEEN 1 AND 6)",
            name="ck_partner_rating_payment_stars_range",
        ),
        CheckConstraint(
            "(payment_expected = false AND payment_discipline_stars IS NULL) OR "
            "(payment_expected = true AND payment_discipline_stars IS NOT NULL)",
            name="ck_partner_rating_payment_expected_contract",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    company_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rated_by_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_quality_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    communication_docs_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_discipline_stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_expected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    short_comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    issue_flags_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class TenantPartnerRatingSummary(Base):
    __tablename__ = "tenant_partner_rating_summary"

    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant_partners.id", ondelete="CASCADE"), primary_key=True)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_execution_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_communication_docs: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_payment_discipline: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_rating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "GlobalCompany",
    "GlobalCompanyReputation",
    "TenantPartner",
    "TenantPartnerRole",
    "TenantPartnerAddress",
    "TenantPartnerBankAccount",
    "TenantPartnerContact",
    "TenantPartnerDocument",
    "PartnerOrderRating",
    "TenantPartnerRatingSummary",
]
