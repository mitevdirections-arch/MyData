from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonTemplateSubmissionStaging
from app.modules.ai.schemas import (
    EidonGlobalPatternSubmissionCandidateDTO,
    EidonSourceTraceabilityDTO,
    EidonStagedTemplateSubmissionRecordDTO,
    EidonTemplateSubmissionStagingRequestDTO,
    EidonTemplateSubmissionStagingResponseDTO,
)

_EXPECTED_LEARNING_RULE = "learn_globally_from_patterns_act_locally_within_tenant_boundaries"
_FORBIDDEN_FEATURE_KEYS: set[str] = {
    "raw_document",
    "raw_payload",
    "raw_content",
    "raw_text",
}
_FORBIDDEN_FEATURE_KEY_TOKENS: tuple[str, ...] = (
    "raw_document",
    "document_text",
    "extracted_text",
    "ocr_text",
    "full_text",
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EidonTemplateSubmissionStagingService:
    def _validate_candidate(self, candidate: EidonGlobalPatternSubmissionCandidateDTO) -> None:
        if not bool(candidate.eligible):
            raise ValueError("submission_candidate_not_eligible")
        if bool(candidate.raw_tenant_document_included):
            raise ValueError("raw_tenant_document_not_allowed")
        if str(candidate.learn_globally_act_locally_rule or "").strip() != _EXPECTED_LEARNING_RULE:
            raise ValueError("template_learning_rule_mismatch")
        if not isinstance(candidate.de_identified_pattern_features, dict) or len(candidate.de_identified_pattern_features) == 0:
            raise ValueError("de_identified_pattern_features_required")

        for k in candidate.de_identified_pattern_features.keys():
            key = str(k or "").strip().lower()
            if key in _FORBIDDEN_FEATURE_KEYS or any(token in key for token in _FORBIDDEN_FEATURE_KEY_TOKENS):
                raise ValueError(f"non_deidentified_feature_key:{k}")

    def _to_traceability(self, items: list[EidonSourceTraceabilityDTO]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for x in items:
            out.append(
                {
                    "field_path": str(x.field_path),
                    "source_class": str(x.source_class),
                    "source_ref": str(x.source_ref),
                }
            )
        return out

    def _staged_record_dto(self, row: EidonTemplateSubmissionStaging) -> EidonStagedTemplateSubmissionRecordDTO:
        source_traceability: list[EidonSourceTraceabilityDTO] = []
        for raw in list(row.source_traceability_json or []):
            source_traceability.append(
                EidonSourceTraceabilityDTO(
                    field_path=str((raw or {}).get("field_path") or ""),
                    source_class=str((raw or {}).get("source_class") or "tenant_user_feedback"),
                    source_ref=str((raw or {}).get("source_ref") or "tenant_feedback:channel=UNKNOWN"),
                )
            )
        created_at = row.created_at if isinstance(row.created_at, datetime) else _now_utc()
        return EidonStagedTemplateSubmissionRecordDTO(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            source_capability=str(row.source_capability),
            submission_shape_version=str(row.submission_shape_version),
            pattern_version=str(row.pattern_version),
            template_fingerprint=str(row.template_fingerprint),
            status=str(row.status),
            review_required=bool(row.review_required),
            quality_score=row.quality_score,
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
            rollback_capable=True,
            rollback_from_submission_id=(str(row.rollback_from_submission_id) if row.rollback_from_submission_id else None),
            raw_tenant_document_included=bool(row.raw_tenant_document_included),
            source_traceability=source_traceability,
            warnings=[str(x) for x in list(row.warnings_json or [])],
            created_at=created_at.isoformat(),
        )

    def stage(
        self,
        *,
        db: Session,
        tenant_id: str,
        actor: str,
        payload: EidonTemplateSubmissionStagingRequestDTO,
    ) -> EidonTemplateSubmissionStagingResponseDTO:
        if not str(tenant_id or "").strip():
            raise ValueError("missing_tenant_context")
        if not bool(payload.human_confirmation_recorded):
            raise ValueError("human_confirmation_required")
        if str(payload.source_template_fingerprint or "").strip() != str(payload.global_pattern_submission_candidate.template_fingerprint or "").strip():
            raise ValueError("template_fingerprint_mismatch")

        candidate = payload.global_pattern_submission_candidate
        self._validate_candidate(candidate)

        staged = EidonTemplateSubmissionStaging(
            id=uuid.uuid4(),
            tenant_id=str(tenant_id),
            source_capability=str(payload.source_capability),
            submission_shape_version=str(payload.submission_shape_version),
            pattern_version=str(candidate.pattern_version),
            template_fingerprint=str(candidate.template_fingerprint),
            status="STAGED_REVIEW_REQUIRED",
            review_required=True,
            quality_score=None,
            authoritative_publish_allowed=False,
            rollback_from_submission_id=None,
            de_identified_pattern_features_json=dict(candidate.de_identified_pattern_features or {}),
            source_traceability_json=self._to_traceability(payload.tenant_source_traceability or []),
            warnings_json=[],
            submission_metadata_json={
                "human_confirmation_recorded": True,
                "submission_blocked_reason": str(candidate.submission_blocked_reason or ""),
            },
            raw_tenant_document_included=False,
            submitted_by=str(actor or "unknown"),
            reviewed_by=None,
            reviewed_at=None,
            review_note=None,
            created_at=_now_utc(),
            updated_at=_now_utc(),
        )
        db.add(staged)
        if hasattr(db, "flush"):
            db.flush()

        staged_record = self._staged_record_dto(staged)
        return EidonTemplateSubmissionStagingResponseDTO(
            ok=True,
            tenant_id=str(tenant_id),
            capability="EIDON_TEMPLATE_SUBMISSION_STAGING_V1",
            staged_submission=staged_record,
            global_pattern_submission_candidate=candidate,
            warnings=list(staged.warnings_json or []),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_template_submission_staging_review_only_no_authoritative_publish",
            no_raw_document_rule="raw_tenant_document_not_allowed_in_template_submission_staging",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonTemplateSubmissionStagingService()
