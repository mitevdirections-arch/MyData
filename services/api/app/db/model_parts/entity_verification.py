from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EntityVerificationTarget(Base):
    __tablename__ = "entity_verification_targets"
    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_entity_verification_target_subject"),
        CheckConstraint("subject_type IN ('TENANT', 'PARTNER', 'EXTERNAL')", name="ck_entity_verification_target_subject_type"),
        Index("ix_entity_verification_target_owner_subject", "owner_company_id", "subject_type"),
        Index("ix_entity_verification_target_global_company", "global_company_id"),
        Index("ix_entity_verification_target_country_vat", "country_code", "vat_number_normalized"),
        Index("ix_entity_verification_target_country_registration", "country_code", "registration_number_normalized"),
        Index("ix_entity_verification_target_country_name", "country_code", "normalized_legal_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_company_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    global_company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("global_companies.id", ondelete="SET NULL"), nullable=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vat_number_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registration_number_normalized: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class EntityVerificationCheck(Base):
    __tablename__ = "entity_verification_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('VERIFIED', 'NOT_VERIFIED', 'UNAVAILABLE', 'NOT_APPLICABLE', 'PARTIAL_MATCH')",
            name="ck_entity_verification_check_status",
        ),
        Index("ix_entity_verification_checks_target_provider_checked", "target_id", "provider_code", "checked_at"),
        Index("ix_entity_verification_checks_target_checked", "target_id", "checked_at"),
        Index("ix_entity_verification_checks_provider_status_checked", "provider_code", "status", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entity_verification_targets.id", ondelete="CASCADE"), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    check_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_message_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_message_text: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EntityVerificationSummary(Base):
    __tablename__ = "entity_verification_summary"
    __table_args__ = (
        CheckConstraint("overall_status IN ('GOOD', 'WARNING', 'PENDING', 'UNKNOWN')", name="ck_entity_verification_summary_status"),
        Index("ix_entity_verification_summary_status_checked", "overall_status", "last_checked_at"),
    )

    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entity_verification_targets.id", ondelete="CASCADE"), primary_key=True)
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_recommended_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unavailable_provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    badges_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class EntityVerificationInflight(Base):
    __tablename__ = "entity_verification_inflight"
    __table_args__ = (
        Index("ix_entity_verification_inflight_lease_expires", "lease_expires_at"),
    )

    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entity_verification_targets.id", ondelete="CASCADE"), primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    lease_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class EntityVerificationProviderState(Base):
    __tablename__ = "entity_verification_provider_state"
    __table_args__ = (
        Index("ix_entity_verification_provider_state_cooldown", "cooldown_until"),
    )

    provider_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "EntityVerificationTarget",
    "EntityVerificationCheck",
    "EntityVerificationSummary",
    "EntityVerificationInflight",
    "EntityVerificationProviderState",
]
