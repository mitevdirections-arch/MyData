from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonPatternActivationRecord, EidonPatternRolloutGovernanceRecord
from app.modules.ai.schemas import (
    EidonPatternActivationRecordDTO,
    EidonPatternActivationRequestDTO,
    EidonPatternActivationResponseDTO,
)

_STATUS_ROLLOUT_GOVERNANCE_RECORDED = "ROLLOUT_GOVERNANCE_RECORDED"
_STATUS_ACTIVATION_RECORDED = "ACTIVATION_RECORDED"
_ELIGIBILITY_ELIGIBLE = "ELIGIBLE"
_FORBIDDEN_META_TOKENS: tuple[str, ...] = (
    "raw_document",
    "raw_payload",
    "raw_text",
    "document_text",
    "extracted_text",
    "source_traceability",
    "corrected_value",
)
_FORBIDDEN_ACTIVATION_GOVERNANCE_TOKENS: tuple[str, ...] = (
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
    "enable_runtime",
    "runtime_enable",
    "go_live",
    "live_enable",
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    ref = dt if isinstance(dt, datetime) else _now_utc()
    return ref.isoformat()


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


def _has_activation_governance_violation(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k or "").strip().lower()
            if any(token in key for token in _FORBIDDEN_ACTIVATION_GOVERNANCE_TOKENS):
                return True
            if _has_activation_governance_violation(v):
                return True
        return False
    if isinstance(obj, list):
        return any(_has_activation_governance_violation(x) for x in obj)
    if isinstance(obj, str):
        lowered = obj.strip().lower()
        return any(token in lowered for token in _FORBIDDEN_ACTIVATION_GOVERNANCE_TOKENS)
    return False


def _sanitize_activation_meta(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("activation_meta_must_be_object")
    if _has_forbidden_content(value):
        raise ValueError("activation_meta_contains_raw_tenant_data")
    if _has_activation_governance_violation(value):
        raise ValueError("activation_meta_governance_violation")
    return dict(value)


def _normalize_activation_note(value: str | None) -> str | None:
    note = str(value or "").strip()
    if not note:
        return None
    if len(note) > 512:
        raise ValueError("activation_note_too_long")
    return note


class EidonPatternActivationService:
    def _load_rollout_governance_record(self, db: Session, record_id: str) -> EidonPatternRolloutGovernanceRecord:
        try:
            parsed = uuid.UUID(str(record_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_rollout_governance_record_id") from exc
        row = db.get(EidonPatternRolloutGovernanceRecord, parsed)
        if row is None:
            raise ValueError("rollout_governance_record_not_found")
        return row

    def _ensure_rollout_governance_record_integrity(self, row: EidonPatternRolloutGovernanceRecord) -> None:
        if bool(row.authoritative_publish_allowed):
            raise ValueError("authoritative_publish_not_allowed")
        if str(row.governance_status or "").strip() != _STATUS_ROLLOUT_GOVERNANCE_RECORDED:
            raise ValueError("rollout_governance_record_status_invalid")
        if not str(row.tenant_id or "").strip():
            raise ValueError("rollout_governance_record_missing_tenant_id")
        if not str(row.template_fingerprint or "").strip():
            raise ValueError("rollout_governance_record_missing_template_fingerprint")
        if not str(row.pattern_version or "").strip():
            raise ValueError("rollout_governance_record_missing_pattern_version")

        meta = row.governance_meta_json
        if not isinstance(meta, dict):
            raise ValueError("rollout_governance_record_metadata_invalid")
        if meta.get("governance_not_rollout_execution") is not True:
            raise ValueError("rollout_governance_record_metadata_invalid")
        if meta.get("governance_not_activation") is not True:
            raise ValueError("rollout_governance_record_metadata_invalid")
        if meta.get("metadata_only") is not True:
            raise ValueError("rollout_governance_record_metadata_invalid")

        payload = meta.get("governance_meta")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("rollout_governance_record_metadata_invalid")
        if _has_forbidden_content(payload):
            raise ValueError("rollout_governance_record_contains_raw_tenant_data")
        if _has_activation_governance_violation(payload):
            raise ValueError("rollout_governance_record_contains_governance_violation")

    def _find_existing_activation_record(
        self,
        db: Session,
        *,
        rollout_governance_record_id: uuid.UUID,
    ) -> EidonPatternActivationRecord | None:
        return (
            db.query(EidonPatternActivationRecord)
            .filter(EidonPatternActivationRecord.rollout_governance_record_id == rollout_governance_record_id)
            .first()
        )

    def _ensure_rollback_reference_exists(self, db: Session, record_id: uuid.UUID | None) -> None:
        if record_id is None:
            return
        row = db.get(EidonPatternActivationRecord, record_id)
        if row is None:
            raise ValueError("rollback_source_activation_record_not_found")

    def _to_record_dto(self, row: EidonPatternActivationRecord) -> EidonPatternActivationRecordDTO:
        return EidonPatternActivationRecordDTO(
            id=str(row.id),
            rollout_governance_record_id=str(row.rollout_governance_record_id),
            tenant_id=str(row.tenant_id),
            template_fingerprint=str(row.template_fingerprint),
            pattern_version=str(row.pattern_version),
            activation_status=str(row.activation_status),
            activation_note=(str(row.activation_note) if row.activation_note is not None else None),
            activation_meta=dict(row.activation_meta_json or {}),
            rollback_from_activation_record_id=(
                str(row.rollback_from_activation_record_id) if row.rollback_from_activation_record_id else None
            ),
            recorded_by=str(row.recorded_by),
            recorded_at=_iso(row.recorded_at),
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
        )

    def record_activation(
        self,
        *,
        db: Session,
        record_id: str,
        actor: str,
        payload: EidonPatternActivationRequestDTO,
    ) -> EidonPatternActivationResponseDTO:
        rollout_governance_row = self._load_rollout_governance_record(db, record_id)
        self._ensure_rollout_governance_record_integrity(rollout_governance_row)

        if str(rollout_governance_row.eligibility_decision or "").strip().upper() != _ELIGIBILITY_ELIGIBLE:
            raise ValueError("rollout_governance_record_not_eligible")

        existing = self._find_existing_activation_record(
            db,
            rollout_governance_record_id=rollout_governance_row.id,
        )
        if existing is not None:
            raise ValueError("activation_record_already_exists")

        activation_note = _normalize_activation_note(payload.activation_note)
        activation_meta = _sanitize_activation_meta(payload.activation_meta)
        rollback_from_activation_record_id = None
        self._ensure_rollback_reference_exists(db, rollback_from_activation_record_id)

        ts = _now_utc()
        row = EidonPatternActivationRecord(
            id=uuid.uuid4(),
            rollout_governance_record_id=rollout_governance_row.id,
            tenant_id=str(rollout_governance_row.tenant_id),
            template_fingerprint=str(rollout_governance_row.template_fingerprint),
            pattern_version=str(rollout_governance_row.pattern_version),
            activation_status=_STATUS_ACTIVATION_RECORDED,
            activation_note=activation_note,
            activation_meta_json={
                "activation_shape_version": "v1",
                "activation_not_runtime_enablement": True,
                "activation_not_worker_execution": True,
                "metadata_only": True,
                "activation_meta": activation_meta,
            },
            rollback_from_activation_record_id=rollback_from_activation_record_id,
            recorded_by=str(actor or "unknown"),
            recorded_at=ts,
            authoritative_publish_allowed=False,
        )
        db.add(row)
        if hasattr(db, "flush"):
            db.flush()

        return EidonPatternActivationResponseDTO(
            ok=True,
            decision=_STATUS_ACTIVATION_RECORDED,
            record=self._to_record_dto(row),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_pattern_activation_metadata_only_no_authoritative_publish",
            no_runtime_enablement_rule="activation_record_creation_does_not_trigger_runtime_enablement",
            no_activation_worker_rule="activation_record_creation_does_not_trigger_worker_or_scheduler",
            no_tenant_runtime_mutation_rule="activation_record_must_not_mutate_tenant_runtime_state",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonPatternActivationService()

