from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonPatternDistributionRecord, EidonPatternPublishArtifact
from app.modules.ai.schemas import (
    EidonPatternDistributionRecordDTO,
    EidonPatternDistributionRecordRequestDTO,
    EidonPatternDistributionResponseDTO,
)

_STATUS_DISTRIBUTION_RECORDED = "DISTRIBUTION_RECORDED"
_FORBIDDEN_META_TOKENS: tuple[str, ...] = (
    "raw_document",
    "raw_payload",
    "raw_text",
    "document_text",
    "extracted_text",
    "source_traceability",
    "corrected_value",
)
_FORBIDDEN_GOVERNANCE_TOKENS: tuple[str, ...] = (
    "tenant_target",
    "tenant_targets",
    "target_list",
    "target_tenants",
    "rollout",
    "rollout_state",
    "rollout_plan",
    "activation",
    "activation_state",
    "activate",
    "auto_activate",
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    ref = dt if isinstance(dt, datetime) else _now_utc()
    return ref.isoformat()


def _parse_optional_uuid(value: str | None, *, err: str) -> uuid.UUID | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(err) from exc


def _has_forbidden_content(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k or "").strip().lower()
            if any(token in key for token in _FORBIDDEN_META_TOKENS):
                return True
            if _has_forbidden_content(v):
                return True
        return False
    if isinstance(obj, list):
        return any(_has_forbidden_content(x) for x in obj)
    if isinstance(obj, str):
        lowered = obj.strip().lower()
        return any(token in lowered for token in _FORBIDDEN_META_TOKENS)
    return False


def _has_governance_violation(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k or "").strip().lower()
            if any(token in key for token in _FORBIDDEN_GOVERNANCE_TOKENS):
                return True
            if _has_governance_violation(v):
                return True
        return False
    if isinstance(obj, list):
        return any(_has_governance_violation(x) for x in obj)
    if isinstance(obj, str):
        lowered = obj.strip().lower()
        return any(token in lowered for token in _FORBIDDEN_GOVERNANCE_TOKENS)
    return False


def _sanitize_distribution_meta(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("distribution_meta_must_be_object")
    if _has_forbidden_content(value):
        raise ValueError("distribution_meta_contains_raw_tenant_data")
    if _has_governance_violation(value):
        raise ValueError("distribution_meta_governance_violation")
    return dict(value)


def _normalize_distribution_note(value: str | None) -> str | None:
    note = str(value or "").strip()
    if not note:
        return None
    if len(note) > 512:
        raise ValueError("distribution_note_too_long")
    return note


class EidonPatternDistributionService:
    def _load_publish_artifact(self, db: Session, artifact_id: str) -> EidonPatternPublishArtifact:
        try:
            parsed = uuid.UUID(str(artifact_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_artifact_id") from exc
        row = db.get(EidonPatternPublishArtifact, parsed)
        if row is None:
            raise ValueError("publish_artifact_not_found")
        return row

    def _ensure_publish_artifact_integrity(self, row: EidonPatternPublishArtifact) -> None:
        if bool(row.authoritative_publish_allowed):
            raise ValueError("authoritative_publish_not_allowed")
        if not str(row.tenant_id or "").strip():
            raise ValueError("publish_artifact_missing_tenant_id")
        if not str(row.template_fingerprint or "").strip():
            raise ValueError("publish_artifact_missing_template_fingerprint")
        if not str(row.pattern_version or "").strip():
            raise ValueError("publish_artifact_missing_pattern_version")

        features = row.de_identified_pattern_features_json
        if not isinstance(features, dict) or len(features) == 0:
            raise ValueError("publish_artifact_deidentified_features_required")
        if _has_forbidden_content(features):
            raise ValueError("publish_artifact_contains_raw_tenant_data")

    def _find_record_by_artifact(
        self,
        db: Session,
        *,
        publish_artifact_id: uuid.UUID,
    ) -> EidonPatternDistributionRecord | None:
        return (
            db.query(EidonPatternDistributionRecord)
            .filter(EidonPatternDistributionRecord.publish_artifact_id == publish_artifact_id)
            .first()
        )

    def _ensure_rollback_reference_exists(self, db: Session, record_id: uuid.UUID | None) -> None:
        if record_id is None:
            return
        row = db.get(EidonPatternDistributionRecord, record_id)
        if row is None:
            raise ValueError("rollback_source_distribution_record_not_found")

    def _to_record_dto(self, row: EidonPatternDistributionRecord) -> EidonPatternDistributionRecordDTO:
        return EidonPatternDistributionRecordDTO(
            id=str(row.id),
            publish_artifact_id=str(row.publish_artifact_id),
            tenant_id=str(row.tenant_id),
            template_fingerprint=str(row.template_fingerprint),
            pattern_version=str(row.pattern_version),
            distribution_status=str(row.distribution_status),
            distribution_note=(str(row.distribution_note) if row.distribution_note is not None else None),
            distribution_meta=dict(row.distribution_meta_json or {}),
            rollback_from_distribution_record_id=(
                str(row.rollback_from_distribution_record_id) if row.rollback_from_distribution_record_id else None
            ),
            recorded_by=str(row.recorded_by),
            recorded_at=_iso(row.recorded_at),
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
        )

    def record_distribution(
        self,
        *,
        db: Session,
        artifact_id: str,
        actor: str,
        payload: EidonPatternDistributionRecordRequestDTO,
    ) -> EidonPatternDistributionResponseDTO:
        artifact = self._load_publish_artifact(db, artifact_id)
        self._ensure_publish_artifact_integrity(artifact)

        existing = self._find_record_by_artifact(db, publish_artifact_id=artifact.id)
        if existing is not None:
            raise ValueError("distribution_record_already_exists")

        rollback_from_distribution_record_id = _parse_optional_uuid(
            payload.rollback_from_distribution_record_id,
            err="invalid_rollback_from_distribution_record_id",
        )
        self._ensure_rollback_reference_exists(db, rollback_from_distribution_record_id)

        distribution_note = _normalize_distribution_note(payload.distribution_note)
        distribution_meta = _sanitize_distribution_meta(payload.distribution_meta)

        ts = _now_utc()
        row = EidonPatternDistributionRecord(
            id=uuid.uuid4(),
            publish_artifact_id=artifact.id,
            tenant_id=str(artifact.tenant_id),
            template_fingerprint=str(artifact.template_fingerprint),
            pattern_version=str(artifact.pattern_version),
            distribution_status=_STATUS_DISTRIBUTION_RECORDED,
            distribution_note=distribution_note,
            distribution_meta_json={
                "distribution_shape_version": "v1",
                "distribution_not_rollout": True,
                "distribution_not_activation": True,
                "metadata_only": True,
                "distribution_meta": distribution_meta,
            },
            rollback_from_distribution_record_id=rollback_from_distribution_record_id,
            recorded_by=str(actor or "unknown"),
            recorded_at=ts,
            authoritative_publish_allowed=False,
        )
        db.add(row)
        if hasattr(db, "flush"):
            db.flush()

        return EidonPatternDistributionResponseDTO(
            ok=True,
            decision="DISTRIBUTION_RECORDED",
            record=self._to_record_dto(row),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_pattern_distribution_metadata_only_no_authoritative_publish",
            no_rollout_rule="distribution_record_creation_does_not_trigger_rollout",
            no_activation_rule="distribution_record_creation_does_not_trigger_activation",
            no_tenant_runtime_mutation_rule="distribution_record_must_not_mutate_tenant_runtime_state",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonPatternDistributionService()
