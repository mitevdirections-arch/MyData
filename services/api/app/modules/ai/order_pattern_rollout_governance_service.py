from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EidonPatternDistributionRecord, EidonPatternRolloutGovernanceRecord
from app.modules.ai.schemas import (
    EidonPatternRolloutGovernanceRecordDTO,
    EidonPatternRolloutGovernanceRequestDTO,
    EidonPatternRolloutGovernanceResponseDTO,
)

_STATUS_DISTRIBUTION_RECORDED = "DISTRIBUTION_RECORDED"
_STATUS_ROLLOUT_GOVERNANCE_RECORDED = "ROLLOUT_GOVERNANCE_RECORDED"
_ALLOWED_ELIGIBILITY_DECISIONS = {"ELIGIBLE", "NOT_ELIGIBLE"}
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


def _sanitize_governance_meta(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("governance_meta_must_be_object")
    if _has_forbidden_content(value):
        raise ValueError("governance_meta_contains_raw_tenant_data")
    if _has_governance_violation(value):
        raise ValueError("governance_meta_governance_violation")
    return dict(value)


def _normalize_governance_note(value: str | None) -> str | None:
    note = str(value or "").strip()
    if not note:
        return None
    if len(note) > 512:
        raise ValueError("governance_note_too_long")
    return note


def _normalize_eligibility_decision(value: str) -> str:
    decision = str(value or "").strip().upper()
    if decision not in _ALLOWED_ELIGIBILITY_DECISIONS:
        raise ValueError("invalid_eligibility_decision")
    return decision


class EidonPatternRolloutGovernanceService:
    def _load_distribution_record(self, db: Session, record_id: str) -> EidonPatternDistributionRecord:
        try:
            parsed = uuid.UUID(str(record_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_distribution_record_id") from exc
        row = db.get(EidonPatternDistributionRecord, parsed)
        if row is None:
            raise ValueError("distribution_record_not_found")
        return row

    def _ensure_distribution_record_integrity(self, row: EidonPatternDistributionRecord) -> None:
        if bool(row.authoritative_publish_allowed):
            raise ValueError("authoritative_publish_not_allowed")
        if str(row.distribution_status or "").strip() != _STATUS_DISTRIBUTION_RECORDED:
            raise ValueError("distribution_record_status_invalid")
        if not str(row.tenant_id or "").strip():
            raise ValueError("distribution_record_missing_tenant_id")
        if not str(row.template_fingerprint or "").strip():
            raise ValueError("distribution_record_missing_template_fingerprint")
        if not str(row.pattern_version or "").strip():
            raise ValueError("distribution_record_missing_pattern_version")

        meta = row.distribution_meta_json
        if not isinstance(meta, dict):
            raise ValueError("distribution_record_metadata_invalid")
        if meta.get("distribution_not_rollout") is not True:
            raise ValueError("distribution_record_metadata_invalid")
        if meta.get("distribution_not_activation") is not True:
            raise ValueError("distribution_record_metadata_invalid")
        if meta.get("metadata_only") is not True:
            raise ValueError("distribution_record_metadata_invalid")

        payload = meta.get("distribution_meta")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("distribution_record_metadata_invalid")

        if _has_forbidden_content(payload):
            raise ValueError("distribution_record_contains_raw_tenant_data")
        if _has_governance_violation(payload):
            raise ValueError("distribution_record_contains_governance_violation")

    def _find_existing_governance_record(
        self,
        db: Session,
        *,
        distribution_record_id: uuid.UUID,
    ) -> EidonPatternRolloutGovernanceRecord | None:
        return (
            db.query(EidonPatternRolloutGovernanceRecord)
            .filter(EidonPatternRolloutGovernanceRecord.distribution_record_id == distribution_record_id)
            .first()
        )

    def _ensure_rollback_reference_exists(self, db: Session, record_id: uuid.UUID | None) -> None:
        if record_id is None:
            return
        row = db.get(EidonPatternRolloutGovernanceRecord, record_id)
        if row is None:
            raise ValueError("rollback_source_governance_record_not_found")

    def _to_record_dto(self, row: EidonPatternRolloutGovernanceRecord) -> EidonPatternRolloutGovernanceRecordDTO:
        return EidonPatternRolloutGovernanceRecordDTO(
            id=str(row.id),
            distribution_record_id=str(row.distribution_record_id),
            tenant_id=str(row.tenant_id),
            template_fingerprint=str(row.template_fingerprint),
            pattern_version=str(row.pattern_version),
            governance_status=str(row.governance_status),
            eligibility_decision=str(row.eligibility_decision),
            governance_note=(str(row.governance_note) if row.governance_note is not None else None),
            governance_meta=dict(row.governance_meta_json or {}),
            rollback_from_governance_record_id=(
                str(row.rollback_from_governance_record_id) if row.rollback_from_governance_record_id else None
            ),
            recorded_by=str(row.recorded_by),
            recorded_at=_iso(row.recorded_at),
            authoritative_publish_allowed=bool(row.authoritative_publish_allowed),
        )

    def record_rollout_governance(
        self,
        *,
        db: Session,
        record_id: str,
        actor: str,
        payload: EidonPatternRolloutGovernanceRequestDTO,
    ) -> EidonPatternRolloutGovernanceResponseDTO:
        distribution_row = self._load_distribution_record(db, record_id)
        self._ensure_distribution_record_integrity(distribution_row)

        existing = self._find_existing_governance_record(db, distribution_record_id=distribution_row.id)
        if existing is not None:
            raise ValueError("rollout_governance_record_already_exists")

        eligibility_decision = _normalize_eligibility_decision(payload.eligibility_decision)
        governance_note = _normalize_governance_note(payload.governance_note)
        governance_meta = _sanitize_governance_meta(payload.governance_meta)
        rollback_from_governance_record_id = None
        self._ensure_rollback_reference_exists(db, rollback_from_governance_record_id)

        ts = _now_utc()
        row = EidonPatternRolloutGovernanceRecord(
            id=uuid.uuid4(),
            distribution_record_id=distribution_row.id,
            tenant_id=str(distribution_row.tenant_id),
            template_fingerprint=str(distribution_row.template_fingerprint),
            pattern_version=str(distribution_row.pattern_version),
            governance_status=_STATUS_ROLLOUT_GOVERNANCE_RECORDED,
            eligibility_decision=eligibility_decision,
            governance_note=governance_note,
            governance_meta_json={
                "governance_shape_version": "v1",
                "governance_not_rollout_execution": True,
                "governance_not_activation": True,
                "metadata_only": True,
                "eligibility_decision": eligibility_decision,
                "governance_meta": governance_meta,
            },
            rollback_from_governance_record_id=rollback_from_governance_record_id,
            recorded_by=str(actor or "unknown"),
            recorded_at=ts,
            authoritative_publish_allowed=False,
        )
        db.add(row)
        if hasattr(db, "flush"):
            db.flush()

        return EidonPatternRolloutGovernanceResponseDTO(
            ok=True,
            decision=_STATUS_ROLLOUT_GOVERNANCE_RECORDED,
            record=self._to_record_dto(row),
            authoritative_publish_allowed=False,
            no_authoritative_publish_rule="eidon_pattern_rollout_governance_metadata_only_no_authoritative_publish",
            no_rollout_rule="rollout_governance_record_creation_does_not_trigger_rollout_execution",
            no_activation_rule="rollout_governance_record_creation_does_not_trigger_activation",
            no_tenant_runtime_mutation_rule="rollout_governance_record_must_not_mutate_tenant_runtime_state",
            system_truth_rule="ai_does_not_override_system_truth",
        )


service = EidonPatternRolloutGovernanceService()
