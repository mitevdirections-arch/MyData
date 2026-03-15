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


__all__ = [
    "EidonTemplateSubmissionStaging",
]
