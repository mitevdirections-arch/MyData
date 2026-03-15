from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import EidonPatternPublishArtifact, EidonTemplateSubmissionStaging
from app.modules.ai.order_template_review_service import STATUS_REVIEW_APPROVED
from app.modules.ai.schemas import (
    EidonPublishedPatternArtifactRecordDTO,
    EidonTemplatePublishRequestDTO,
    EidonTemplatePublishResponseDTO,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class EidonTemplatePublishService:
    def _parse_submission_id(self, submission_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(submission_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_submission_id") from exc

    def _parse_optional_submission_id(self, submission_id: str | None) -> uuid.UUID | None:
        raw = str(submission_id or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_rollback_from_submission_id") from exc

    def _load_submission(self, db: Session, submission_id: str) -> EidonTemplateSubmissionStaging:
        sid = self._parse_submission_id(submission_id)
        row = db.get(EidonTemplateSubmissionStaging, sid)
        if row is None:
            raise ValueError("submission_not_found")
        return row

    def _find_existing_artifact(self, db: Session, source_submission_id: uuid.UUID) -> EidonPatternPublishArtifact | None:
        return (
            db.query(EidonPatternPublishArtifact)
            .filter(EidonPatternPublishArtifact.source_submission_id == source_submission_id)
            .first()
        )

    def _validate_submission_for_publish(self, row: EidonTemplateSubmissionStaging) -> None:
        if str(row.status) != STATUS_REVIEW_APPROVED:
            raise ValueError("publish_requires_review_approved_status")
        if bool(row.raw_tenant_document_included):
            raise ValueError("raw_tenant_document_not_allowed")
        if bool(row.authoritative_publish_allowed):
            raise ValueError("authoritative_publish_not_allowed")
        if row.quality_score is None:
            raise ValueError("quality_score_required_for_publish")

        features = row.de_identified_pattern_features_json
        if not isinstance(features, dict) or len(features) == 0:
            raise ValueError("de_identified_pattern_features_required")
        if not str(row.template_fingerprint or "").strip():
            raise ValueError("template_fingerprint_required")
        if not str(row.pattern_version or "").strip():
            raise ValueError("pattern_version_required")

    def _artifact_dto(
        self,
        *,
        artifact: EidonPatternPublishArtifact,
        source_submission_status: str,
    ) -> EidonPublishedPatternArtifactRecordDTO:
        published_at = artifact.published_at if isinstance(artifact.published_at, datetime) else _now_utc()
        created_at = artifact.created_at if isinstance(artifact.created_at, datetime) else _now_utc()
        return EidonPublishedPatternArtifactRecordDTO(
            id=str(artifact.id),
            source_submission_id=str(artifact.source_submission_id),
            tenant_id=str(artifact.tenant_id),
            source_capability=str(artifact.source_capability),
            submission_shape_version=str(artifact.submission_shape_version),
            source_submission_status=str(source_submission_status),
            pattern_version=str(artifact.pattern_version),
            template_fingerprint=str(artifact.template_fingerprint),
            quality_score=int(artifact.quality_score),
            de_identified_pattern_features=dict(artifact.de_identified_pattern_features_json or {}),
            authoritative_publish_allowed=bool(artifact.authoritative_publish_allowed),
            rollback_capable=bool(artifact.rollback_capable),
            rollback_from_submission_id=(
                str(artifact.rollback_from_submission_id) if artifact.rollback_from_submission_id else None
            ),
            published_by=str(artifact.published_by),
            published_at=published_at.isoformat(),
            created_at=created_at.isoformat(),
            warnings=[],
        )

    def publish(
        self,
        *,
        db: Session,
        submission_id: str,
        actor: str,
        payload: EidonTemplatePublishRequestDTO,
    ) -> EidonTemplatePublishResponseDTO:
        source = self._load_submission(db, submission_id)
        self._validate_submission_for_publish(source)

        existing = self._find_existing_artifact(db, source.id)
        if existing is not None:
            raise ValueError("publish_artifact_already_exists")

        rollback_from_submission_id = self._parse_optional_submission_id(payload.rollback_from_submission_id)
        ts = _now_utc()
        artifact = EidonPatternPublishArtifact(
            id=uuid.uuid4(),
            source_submission_id=source.id,
            tenant_id=str(source.tenant_id),
            source_capability=str(source.source_capability),
            submission_shape_version=str(source.submission_shape_version),
            pattern_version=str(source.pattern_version),
            template_fingerprint=str(source.template_fingerprint),
            quality_score=int(source.quality_score or 0),
            de_identified_pattern_features_json=dict(source.de_identified_pattern_features_json or {}),
            authoritative_publish_allowed=False,
            rollback_capable=True,
            rollback_from_submission_id=rollback_from_submission_id,
            rollback_metadata_json={
                "mode": "metadata_only",
                "engine_enabled": False,
                "rollback_from_submission_id": (
                    str(rollback_from_submission_id) if rollback_from_submission_id else None
                ),
            },
            publish_metadata_json={
                "publish_shape_version": str(payload.publish_shape_version or "v1"),
                "publish_note": str(payload.publish_note or "").strip() or None,
                "source_submission_status": str(source.status),
                "publish_not_rollout": True,
            },
            published_by=str(actor or "unknown"),
            published_at=ts,
            created_at=ts,
        )

        db.add(artifact)
        if hasattr(db, "flush"):
            db.flush()

        return EidonTemplatePublishResponseDTO(
            ok=True,
            decision="PUBLISH_ARTIFACT_CREATED",
            artifact=self._artifact_dto(artifact=artifact, source_submission_status=str(source.status)),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_pattern_publish_metadata_only_no_authoritative_publish",
            no_raw_document_rule="raw_tenant_document_not_allowed_in_publish_artifact",
            no_rollout_rule="publish_artifact_creation_does_not_trigger_distribution_or_rollout",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonTemplatePublishService()
