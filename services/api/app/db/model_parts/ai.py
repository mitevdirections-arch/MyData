from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EidonTemplateSubmissionStaging(Base):
    __tablename__ = "eidon_template_submission_staging"
    __table_args__ = (
        Index("ix_eidon_tpl_stage_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_eidon_tpl_stage_fingerprint_version_created", "template_fingerprint", "pattern_version", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    source_capability: Mapped[str] = mapped_column(String(64), nullable=False, default="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1")
    submission_shape_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    pattern_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1-feedback")
    template_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="STAGED_REVIEW_REQUIRED")
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authoritative_publish_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_from_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    de_identified_pattern_features_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_traceability_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    submission_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_tenant_document_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    submitted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class EidonPatternPublishArtifact(Base):
    __tablename__ = "eidon_pattern_publish_artifacts"
    __table_args__ = (
        Index("ix_eidon_publish_tenant_created", "tenant_id", "created_at"),
        Index("ix_eidon_publish_fingerprint_version_published", "template_fingerprint", "pattern_version", "published_at"),
        Index("ix_eidon_publish_source_submission_unique", "source_submission_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    source_submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eidon_template_submission_staging.id"),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    source_capability: Mapped[str] = mapped_column(String(64), nullable=False, default="EIDON_ORDER_INTAKE_FEEDBACK_LOOP_V1")
    submission_shape_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    pattern_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1-feedback")
    template_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    de_identified_pattern_features_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    authoritative_publish_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_capable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rollback_from_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rollback_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    publish_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    published_by: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class EidonAIQualityEvent(Base):
    __tablename__ = "eidon_ai_quality_events"
    __table_args__ = (
        Index("ix_eidon_ai_quality_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_eidon_ai_quality_events_type_created", "event_type", "created_at"),
        Index("ix_eidon_ai_quality_events_fingerprint_created", "template_fingerprint", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="ORDER_INTAKE_FEEDBACK_V1")
    template_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corrected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_confirmation_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_adjustments_summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


__all__ = [
    "EidonTemplateSubmissionStaging",
    "EidonPatternPublishArtifact",
    "EidonAIQualityEvent",
]
