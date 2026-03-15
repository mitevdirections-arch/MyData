from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import EidonTemplateSubmissionStaging
from app.modules.ai.schemas import (
    EidonSourceTraceabilityDTO,
    EidonTemplateReviewDecisionResponseDTO,
    EidonTemplateReviewQueueItemDTO,
    EidonTemplateReviewQueueResponseDTO,
    EidonTemplateReviewReadResponseDTO,
    EidonTemplateReviewRecordDTO,
)

STATUS_STAGED_REVIEW_REQUIRED = "STAGED_REVIEW_REQUIRED"
STATUS_REVIEW_APPROVED = "REVIEW_APPROVED"
STATUS_REVIEW_REJECTED = "REVIEW_REJECTED"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EidonTemplateReviewService:
    def _parse_uuid(self, submission_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(submission_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_submission_id") from exc

    def _iso(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    def _traceability_dto(self, row: EidonTemplateSubmissionStaging) -> list[EidonSourceTraceabilityDTO]:
        items: list[EidonSourceTraceabilityDTO] = []
        for raw in list(row.source_traceability_json or []):
            items.append(
                EidonSourceTraceabilityDTO(
                    field_path=str((raw or {}).get("field_path") or ""),
                    source_class=str((raw or {}).get("source_class") or "tenant_user_feedback"),
                    source_ref=str((raw or {}).get("source_ref") or "tenant_feedback:channel=UNKNOWN"),
                )
            )
        return items

    def _queue_item(self, row: EidonTemplateSubmissionStaging) -> EidonTemplateReviewQueueItemDTO:
        return EidonTemplateReviewQueueItemDTO(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            source_capability=str(row.source_capability),
            submission_shape_version=str(row.submission_shape_version),
            pattern_version=str(row.pattern_version),
            template_fingerprint=str(row.template_fingerprint),
            status=str(row.status),
            review_required=bool(row.review_required),
            quality_score=row.quality_score,
            submitted_by=row.submitted_by,
            reviewed_by=row.reviewed_by,
            reviewed_at=self._iso(row.reviewed_at),
            created_at=self._iso(row.created_at) or _now_utc().isoformat(),
            updated_at=self._iso(row.updated_at) or _now_utc().isoformat(),
            raw_tenant_document_included=bool(row.raw_tenant_document_included),
        )

    def _record(self, row: EidonTemplateSubmissionStaging) -> EidonTemplateReviewRecordDTO:
        q = self._queue_item(row)
        return EidonTemplateReviewRecordDTO(
            **q.model_dump(),
            review_note=row.review_note,
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
            rollback_capable=True,
            rollback_from_submission_id=(str(row.rollback_from_submission_id) if row.rollback_from_submission_id else None),
            source_traceability=self._traceability_dto(row),
            warnings=[str(x) for x in list(row.warnings_json or [])],
        )

    def _load(self, db: Session, submission_id: str) -> EidonTemplateSubmissionStaging:
        sid = self._parse_uuid(submission_id)
        row = db.get(EidonTemplateSubmissionStaging, sid)
        if row is None:
            raise ValueError("submission_not_found")
        return row

    def list_queue(
        self,
        *,
        db: Session,
        limit: int = 50,
        status: str | None = STATUS_STAGED_REVIEW_REQUIRED,
    ) -> EidonTemplateReviewQueueResponseDTO:
        cap = max(1, min(int(limit), 500))
        q = db.query(EidonTemplateSubmissionStaging)
        if status is not None and str(status).strip():
            q = q.filter(EidonTemplateSubmissionStaging.status == str(status).strip())
        rows: Iterable[EidonTemplateSubmissionStaging] = q.order_by(EidonTemplateSubmissionStaging.created_at.desc()).limit(cap).all()
        return EidonTemplateReviewQueueResponseDTO(ok=True, items=[self._queue_item(x) for x in rows])

    def read_submission(self, *, db: Session, submission_id: str) -> EidonTemplateReviewReadResponseDTO:
        row = self._load(db, submission_id)
        return EidonTemplateReviewReadResponseDTO(ok=True, submission=self._record(row))

    def approve(
        self,
        *,
        db: Session,
        submission_id: str,
        actor: str,
        review_note: str | None,
        quality_score: int | None,
    ) -> EidonTemplateReviewDecisionResponseDTO:
        row = self._load(db, submission_id)
        if str(row.status) != STATUS_STAGED_REVIEW_REQUIRED:
            raise ValueError("invalid_status_transition")
        if quality_score is None:
            raise ValueError("quality_score_required_for_approval")
        if not bool(row.review_required):
            raise ValueError("review_not_required_state_invalid")
        if bool(row.raw_tenant_document_included):
            raise ValueError("raw_tenant_document_not_allowed")

        row.status = STATUS_REVIEW_APPROVED
        row.quality_score = int(quality_score)
        row.review_note = str(review_note or "").strip() or None
        row.reviewed_by = str(actor or "unknown")
        row.reviewed_at = _now_utc()
        row.updated_at = _now_utc()
        row.authoritative_publish_allowed = False

        return EidonTemplateReviewDecisionResponseDTO(ok=True, decision="APPROVE", submission=self._record(row))

    def reject(
        self,
        *,
        db: Session,
        submission_id: str,
        actor: str,
        review_note: str | None,
        quality_score: int | None,
    ) -> EidonTemplateReviewDecisionResponseDTO:
        row = self._load(db, submission_id)
        if str(row.status) != STATUS_STAGED_REVIEW_REQUIRED:
            raise ValueError("invalid_status_transition")
        note = str(review_note or "").strip()
        if not note:
            raise ValueError("review_note_required_for_reject")
        if not bool(row.review_required):
            raise ValueError("review_not_required_state_invalid")

        row.status = STATUS_REVIEW_REJECTED
        row.quality_score = (int(quality_score) if quality_score is not None else row.quality_score)
        row.review_note = note
        row.reviewed_by = str(actor or "unknown")
        row.reviewed_at = _now_utc()
        row.updated_at = _now_utc()
        row.authoritative_publish_allowed = False

        return EidonTemplateReviewDecisionResponseDTO(ok=True, decision="REJECT", submission=self._record(row))


service = EidonTemplateReviewService()
