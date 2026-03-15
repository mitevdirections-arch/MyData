from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonPatternActivationRecord, EidonRuntimeEnablementRecord
from app.modules.ai.schemas import (
    EidonRuntimeEnablementRecordDTO,
    EidonRuntimeEnablementRequestDTO,
    EidonRuntimeEnablementResponseDTO,
)

_STATUS_ACTIVATION_RECORDED = "ACTIVATION_RECORDED"
_STATUS_RUNTIME_ENABLEMENT_RECORDED = "RUNTIME_ENABLEMENT_RECORDED"
_ALLOWED_RUNTIME_DECISIONS = {"ENABLEABLE", "NOT_ENABLEABLE"}
_FORBIDDEN_META_TOKENS: tuple[str, ...] = (
    "raw_document",
    "raw_payload",
    "raw_text",
    "document_text",
    "extracted_text",
    "source_traceability",
    "corrected_value",
)
_FORBIDDEN_RUNTIME_GOVERNANCE_TOKENS: tuple[str, ...] = (
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
    "enable_now",
    "runtime_apply",
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


def _has_runtime_enablement_governance_violation(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k or "").strip().lower()
            if any(token in key for token in _FORBIDDEN_RUNTIME_GOVERNANCE_TOKENS):
                return True
            if _has_runtime_enablement_governance_violation(v):
                return True
        return False
    if isinstance(obj, list):
        return any(_has_runtime_enablement_governance_violation(x) for x in obj)
    if isinstance(obj, str):
        lowered = obj.strip().lower()
        return any(token in lowered for token in _FORBIDDEN_RUNTIME_GOVERNANCE_TOKENS)
    return False


def _sanitize_runtime_meta(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("runtime_meta_must_be_object")
    if _has_forbidden_content(value):
        raise ValueError("runtime_meta_contains_raw_tenant_data")
    if _has_runtime_enablement_governance_violation(value):
        raise ValueError("runtime_meta_governance_violation")
    return dict(value)


def _normalize_runtime_note(value: str | None) -> str | None:
    note = str(value or "").strip()
    if not note:
        return None
    if len(note) > 512:
        raise ValueError("runtime_note_too_long")
    return note


def _normalize_runtime_decision(value: str) -> str:
    decision = str(value or "").strip().upper()
    if decision not in _ALLOWED_RUNTIME_DECISIONS:
        raise ValueError("invalid_runtime_decision")
    return decision


class EidonRuntimeEnablementService:
    def _load_activation_record(self, db: Session, record_id: str) -> EidonPatternActivationRecord:
        try:
            parsed = uuid.UUID(str(record_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_activation_record_id") from exc
        row = db.get(EidonPatternActivationRecord, parsed)
        if row is None:
            raise ValueError("activation_record_not_found")
        return row

    def _ensure_activation_record_integrity(self, row: EidonPatternActivationRecord) -> None:
        if bool(row.authoritative_publish_allowed):
            raise ValueError("authoritative_publish_not_allowed")
        if str(row.activation_status or "").strip() != _STATUS_ACTIVATION_RECORDED:
            raise ValueError("activation_record_status_invalid")
        if not str(row.tenant_id or "").strip():
            raise ValueError("activation_record_missing_tenant_id")
        if not str(row.template_fingerprint or "").strip():
            raise ValueError("activation_record_missing_template_fingerprint")
        if not str(row.pattern_version or "").strip():
            raise ValueError("activation_record_missing_pattern_version")

        meta = row.activation_meta_json
        if not isinstance(meta, dict):
            raise ValueError("activation_record_metadata_invalid")
        if meta.get("activation_not_runtime_enablement") is not True:
            raise ValueError("activation_record_metadata_invalid")
        if meta.get("activation_not_worker_execution") is not True:
            raise ValueError("activation_record_metadata_invalid")
        if meta.get("metadata_only") is not True:
            raise ValueError("activation_record_metadata_invalid")

        payload = meta.get("activation_meta")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("activation_record_metadata_invalid")
        if _has_forbidden_content(payload):
            raise ValueError("activation_record_contains_raw_tenant_data")
        if _has_runtime_enablement_governance_violation(payload):
            raise ValueError("activation_record_contains_governance_violation")

    def _find_existing_runtime_enablement_record(
        self,
        db: Session,
        *,
        activation_record_id: uuid.UUID,
    ) -> EidonRuntimeEnablementRecord | None:
        return (
            db.query(EidonRuntimeEnablementRecord)
            .filter(EidonRuntimeEnablementRecord.activation_record_id == activation_record_id)
            .first()
        )

    def _ensure_rollback_reference_exists(self, db: Session, record_id: uuid.UUID | None) -> None:
        if record_id is None:
            return
        row = db.get(EidonRuntimeEnablementRecord, record_id)
        if row is None:
            raise ValueError("rollback_source_runtime_enablement_record_not_found")

    def _to_record_dto(self, row: EidonRuntimeEnablementRecord) -> EidonRuntimeEnablementRecordDTO:
        return EidonRuntimeEnablementRecordDTO(
            id=str(row.id),
            activation_record_id=str(row.activation_record_id),
            tenant_id=str(row.tenant_id),
            template_fingerprint=str(row.template_fingerprint),
            pattern_version=str(row.pattern_version),
            runtime_enablement_status=str(row.runtime_enablement_status),
            runtime_decision=str(row.runtime_decision),
            runtime_note=(str(row.runtime_note) if row.runtime_note is not None else None),
            runtime_meta=dict(row.runtime_meta_json or {}),
            rollback_from_runtime_enablement_record_id=(
                str(row.rollback_from_runtime_enablement_record_id)
                if row.rollback_from_runtime_enablement_record_id
                else None
            ),
            recorded_by=str(row.recorded_by),
            recorded_at=_iso(row.recorded_at),
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
        )

    def record_runtime_enablement(
        self,
        *,
        db: Session,
        record_id: str,
        actor: str,
        payload: EidonRuntimeEnablementRequestDTO,
    ) -> EidonRuntimeEnablementResponseDTO:
        activation_row = self._load_activation_record(db, record_id)
        self._ensure_activation_record_integrity(activation_row)

        existing = self._find_existing_runtime_enablement_record(
            db,
            activation_record_id=activation_row.id,
        )
        if existing is not None:
            raise ValueError("runtime_enablement_record_already_exists")

        runtime_decision = _normalize_runtime_decision(payload.runtime_decision)
        runtime_note = _normalize_runtime_note(payload.runtime_note)
        runtime_meta = _sanitize_runtime_meta(payload.runtime_meta)
        rollback_from_runtime_enablement_record_id = None
        self._ensure_rollback_reference_exists(db, rollback_from_runtime_enablement_record_id)

        ts = _now_utc()
        row = EidonRuntimeEnablementRecord(
            id=uuid.uuid4(),
            activation_record_id=activation_row.id,
            tenant_id=str(activation_row.tenant_id),
            template_fingerprint=str(activation_row.template_fingerprint),
            pattern_version=str(activation_row.pattern_version),
            runtime_enablement_status=_STATUS_RUNTIME_ENABLEMENT_RECORDED,
            runtime_decision=runtime_decision,
            runtime_note=runtime_note,
            runtime_meta_json={
                "runtime_enablement_shape_version": "v1",
                "runtime_enablement_not_actual_runtime_enablement": True,
                "runtime_enablement_not_worker_execution": True,
                "metadata_only": True,
                "runtime_decision": runtime_decision,
                "runtime_meta": runtime_meta,
            },
            rollback_from_runtime_enablement_record_id=rollback_from_runtime_enablement_record_id,
            recorded_by=str(actor or "unknown"),
            recorded_at=ts,
            authoritative_publish_allowed=False,
        )
        db.add(row)
        if hasattr(db, "flush"):
            db.flush()

        return EidonRuntimeEnablementResponseDTO(
            ok=True,
            decision=_STATUS_RUNTIME_ENABLEMENT_RECORDED,
            record=self._to_record_dto(row),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_runtime_enablement_metadata_only_no_authoritative_publish",
            no_actual_runtime_enablement_rule="runtime_enablement_record_creation_does_not_trigger_actual_runtime_enablement",
            no_runtime_worker_rule="runtime_enablement_record_creation_does_not_trigger_worker_or_scheduler",
            no_tenant_runtime_mutation_rule="runtime_enablement_record_must_not_mutate_tenant_runtime_state",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonRuntimeEnablementService()
