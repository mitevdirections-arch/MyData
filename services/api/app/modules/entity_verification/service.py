from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.perf_profile import record_segment
from app.core.settings import get_settings
from app.db.models import (
    EntityVerificationCheck,
    EntityVerificationInflight,
    EntityVerificationProviderState,
    EntityVerificationSummary,
    EntityVerificationTarget,
)
from app.modules.entity_verification.normalization import (
    get_vies_applicability_status,
    normalize_address_lite,
    normalize_country_code,
    normalize_legal_name,
    normalize_legal_name_key,
    normalize_registration_number,
    normalize_vat_number,
)
from app.modules.entity_verification.schemas import (
    InflightAcquireResultDTO,
    ProviderCheckResultDTO,
    ProviderStatus,
    SummaryStatus,
    VerificationProviderRunDTO,
    VerificationCheckDTO,
    VerificationSummaryDTO,
    VerificationTargetDTO,
    VerificationTargetUpsertInput,
    ViesApplicabilityStatus,
)
from app.modules.entity_verification.providers.vies import VIESProviderAdapter, build_default_vies_execution_client

TTL_VERIFIED_HOURS_ENV = "MYDATA_ENTITY_VERIFICATION_TTL_VERIFIED_HOURS"
TTL_NOT_VERIFIED_HOURS_ENV = "MYDATA_ENTITY_VERIFICATION_TTL_NOT_VERIFIED_HOURS"
TTL_UNAVAILABLE_MINUTES_ENV = "MYDATA_ENTITY_VERIFICATION_TTL_UNAVAILABLE_MINUTES"
INFLIGHT_TTL_SECONDS_ENV = "MYDATA_ENTITY_VERIFICATION_INFLIGHT_TTL_SECONDS"
RECHECK_COOLDOWN_SECONDS_ENV = "MYDATA_ENTITY_VERIFICATION_RECHECK_COOLDOWN_SECONDS"
IDEMPOTENCY_TTL_SECONDS_ENV = "MYDATA_ENTITY_VERIFICATION_IDEMPOTENCY_TTL_SECONDS"
PROVIDER_COOLDOWN_SECONDS_ENV = "MYDATA_ENTITY_VERIFICATION_PROVIDER_COOLDOWN_SECONDS"
MANUAL_CHECK_WINDOW_SECONDS_ENV = "MYDATA_ENTITY_VERIFICATION_MANUAL_CHECK_WINDOW_SECONDS"
MANUAL_CHECK_WINDOW_MAX_ENV = "MYDATA_ENTITY_VERIFICATION_MANUAL_CHECK_WINDOW_MAX"
MANUAL_CHECK_WINDOW_USER_MAX_ENV = "MYDATA_ENTITY_VERIFICATION_MANUAL_CHECK_WINDOW_USER_MAX"

DEFAULT_TTL_VERIFIED_HOURS = 168
DEFAULT_TTL_NOT_VERIFIED_HOURS = 24
DEFAULT_TTL_UNAVAILABLE_MINUTES = 15
DEFAULT_INFLIGHT_TTL_SECONDS = 120
DEFAULT_RECHECK_COOLDOWN_SECONDS = 60
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 120
DEFAULT_PROVIDER_COOLDOWN_SECONDS = 60
DEFAULT_MANUAL_CHECK_WINDOW_SECONDS = 300
DEFAULT_MANUAL_CHECK_WINDOW_MAX = 20
DEFAULT_MANUAL_CHECK_WINDOW_USER_MAX = 20
DEFAULT_CIRCUIT_WINDOW_MINUTES = 10
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
MAX_EVIDENCE_PAYLOAD_BYTES = 16 * 1024

EVIDENCE_ALLOWLIST: set[str] = {
    "member_state_code",
    "vat_number_normalized",
    "vies_valid",
    "name_match_status",
    "address_match_status",
    "consultation_reference",
    "provider_raw_status",
    "provider_error_code",
    "provider_error_message",
    "provider_reason",
    "source",
    "reason",
    "detail",
    "country_code",
    "registration_number_normalized",
    "normalized_legal_name",
    "match_basis",
    "request_id",
    "provider_payload_version",
    "applicability_status",
    "provider_call_skipped",
    "provider_call_ms",
}


def _env_int(name: str, default: int, *, min_value: int) -> int:
    try:
        value = int(str(os.getenv(name, str(default))).strip())
        return max(min_value, value)
    except Exception:  # noqa: BLE001
        return max(min_value, default)


class EntityVerificationService:
    """Phase 1B foundation for target lifecycle, inflight control and summary recompute."""

    def __init__(self) -> None:
        settings = get_settings()
        self.ttl_verified_hours = _env_int(TTL_VERIFIED_HOURS_ENV, DEFAULT_TTL_VERIFIED_HOURS, min_value=1)
        self.ttl_not_verified_hours = _env_int(TTL_NOT_VERIFIED_HOURS_ENV, DEFAULT_TTL_NOT_VERIFIED_HOURS, min_value=1)
        self.ttl_unavailable_minutes = _env_int(TTL_UNAVAILABLE_MINUTES_ENV, DEFAULT_TTL_UNAVAILABLE_MINUTES, min_value=1)
        self.inflight_ttl_seconds = _env_int(INFLIGHT_TTL_SECONDS_ENV, DEFAULT_INFLIGHT_TTL_SECONDS, min_value=1)
        self.recheck_cooldown_seconds = _env_int(RECHECK_COOLDOWN_SECONDS_ENV, DEFAULT_RECHECK_COOLDOWN_SECONDS, min_value=1)
        self.idempotency_ttl_seconds = _env_int(IDEMPOTENCY_TTL_SECONDS_ENV, DEFAULT_IDEMPOTENCY_TTL_SECONDS, min_value=1)
        self.provider_cooldown_seconds = _env_int(PROVIDER_COOLDOWN_SECONDS_ENV, DEFAULT_PROVIDER_COOLDOWN_SECONDS, min_value=1)
        self.manual_check_window_seconds = _env_int(
            MANUAL_CHECK_WINDOW_SECONDS_ENV,
            DEFAULT_MANUAL_CHECK_WINDOW_SECONDS,
            min_value=1,
        )
        self.manual_check_window_max = _env_int(
            MANUAL_CHECK_WINDOW_MAX_ENV,
            DEFAULT_MANUAL_CHECK_WINDOW_MAX,
            min_value=1,
        )
        self.manual_check_window_user_max = _env_int(
            MANUAL_CHECK_WINDOW_USER_MAX_ENV,
            DEFAULT_MANUAL_CHECK_WINDOW_USER_MAX,
            min_value=1,
        )
        self.provider_circuit_window_minutes = DEFAULT_CIRCUIT_WINDOW_MINUTES
        self.provider_circuit_failure_threshold = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
        self.vies_enabled = bool(getattr(settings, "entity_verification_vies_enabled", False))
        self.vies_wsdl_url = str(
            getattr(
                settings,
                "entity_verification_vies_wsdl_url",
                "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl",
            )
            or "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"
        ).strip()
        self.vies_service_url = str(
            getattr(
                settings,
                "entity_verification_vies_service_url",
                "https://ec.europa.eu/taxation_customs/vies/services/checkVatService",
            )
            or "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
        ).strip()
        self.vies_connect_timeout_seconds = int(getattr(settings, "entity_verification_vies_connect_timeout_seconds", 2))
        self.vies_read_timeout_seconds = int(getattr(settings, "entity_verification_vies_read_timeout_seconds", 4))
        self.vies_total_budget_seconds = int(getattr(settings, "entity_verification_vies_total_budget_seconds", 7))
        self.vies_retry_count = int(getattr(settings, "entity_verification_vies_retry_count", 1))
        self.vies_retry_backoff_ms = int(getattr(settings, "entity_verification_vies_retry_backoff_ms", 300))
        self.vies_cooldown_seconds = int(getattr(settings, "entity_verification_vies_cooldown_seconds", 60))

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _clean(self, value: object, size: int) -> str:
        return str(value or "").strip()[:size]

    def _clean_opt(self, value: object, size: int) -> str | None:
        out = self._clean(value, size)
        return out if out else None

    def _parse_target_uuid(self, value: str | uuid.UUID) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("target_id_invalid") from exc

    def _parse_opt_uuid(self, value: str | uuid.UUID | None, *, field: str) -> uuid.UUID | None:
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{field}_invalid") from exc

    def _provider_status(self, value: ProviderStatus | str) -> ProviderStatus:
        if isinstance(value, ProviderStatus):
            return value
        try:
            return ProviderStatus(str(value).strip().upper())
        except Exception as exc:  # noqa: BLE001
            raise ValueError("provider_status_invalid") from exc

    def _summary_status(self, value: SummaryStatus | str) -> SummaryStatus:
        if isinstance(value, SummaryStatus):
            return value
        return SummaryStatus(str(value).strip().upper())

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            if isinstance(value, str):
                return value[:2048]
            return value
        if isinstance(value, list):
            return [self._json_safe(v) for v in list(value)[:32]]
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in list(value)[:32]]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for idx, (k, v) in enumerate(dict(value).items()):
                if idx >= 64:
                    break
                key = self._clean(str(k).strip(), 64)
                if not key:
                    continue
                out[key] = self._json_safe(v)
            return out
        return self._clean(str(value), 2048)

    def _sanitize_evidence(self, evidence_json: dict[str, Any] | None) -> dict[str, Any]:
        src = dict(evidence_json or {})
        out: dict[str, Any] = {}
        for raw_key, raw_value in src.items():
            key = self._clean(str(raw_key).strip(), 64)
            if not key:
                continue
            if key not in EVIDENCE_ALLOWLIST:
                continue
            # Fail-fast on very large single evidence values before truncation.
            if isinstance(raw_value, str):
                if len(raw_value.encode("utf-8")) > MAX_EVIDENCE_PAYLOAD_BYTES:
                    raise ValueError("evidence_payload_too_large")
            elif isinstance(raw_value, (list, tuple, dict)):
                raw_blob = json.dumps(raw_value, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
                if len(raw_blob) > MAX_EVIDENCE_PAYLOAD_BYTES:
                    raise ValueError("evidence_payload_too_large")
            out[key] = self._json_safe(raw_value)
        payload_bytes = len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if payload_bytes > MAX_EVIDENCE_PAYLOAD_BYTES:
            raise ValueError("evidence_payload_too_large")
        return out

    def _target_to_dto(self, row: EntityVerificationTarget) -> VerificationTargetDTO:
        return VerificationTargetDTO(
            id=str(row.id),
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            owner_company_id=row.owner_company_id,
            global_company_id=(str(row.global_company_id) if row.global_company_id else None),
            legal_name=row.legal_name,
            normalized_legal_name=row.normalized_legal_name,
            country_code=row.country_code,
            vat_number=row.vat_number,
            vat_number_normalized=row.vat_number_normalized,
            registration_number=row.registration_number,
            registration_number_normalized=row.registration_number_normalized,
            address_line=row.address_line,
            postal_code=row.postal_code,
            city=row.city,
            website_url=row.website_url,
            created_at=(row.created_at.isoformat() if row.created_at else None),
            updated_at=(row.updated_at.isoformat() if row.updated_at else None),
        )

    def get_target(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
    ) -> VerificationTargetDTO:
        tid = self._parse_target_uuid(target_id)
        row = db.query(EntityVerificationTarget).filter(EntityVerificationTarget.id == tid).first()
        if row is None:
            raise ValueError("target_not_found")
        return self._target_to_dto(row)

    def _check_to_dto(self, row: EntityVerificationCheck) -> VerificationCheckDTO:
        return VerificationCheckDTO(
            id=str(row.id),
            target_id=str(row.target_id),
            provider_code=row.provider_code,
            check_type=row.check_type,
            status=self._provider_status(row.status),
            checked_at=row.checked_at.isoformat(),
            expires_at=(row.expires_at.isoformat() if row.expires_at else None),
            match_score=row.match_score,
            provider_reference=row.provider_reference,
            provider_message_code=row.provider_message_code,
            provider_message_text=row.provider_message_text,
            evidence_json=dict(row.evidence_json or {}),
            created_by_user_id=row.created_by_user_id,
        )

    def list_checks(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        limit: int = 100,
    ) -> list[VerificationCheckDTO]:
        tid = self._parse_target_uuid(target_id)
        lim = max(1, min(20, int(limit)))
        rows = (
            db.query(EntityVerificationCheck)
            .filter(EntityVerificationCheck.target_id == tid)
            .order_by(EntityVerificationCheck.checked_at.desc())
            .limit(lim)
            .all()
        )
        return [self._check_to_dto(x) for x in rows]

    def _summary_to_dto(self, row: EntityVerificationSummary) -> VerificationSummaryDTO:
        return VerificationSummaryDTO(
            target_id=str(row.target_id),
            overall_status=self._summary_status(row.overall_status),
            last_checked_at=(row.last_checked_at.isoformat() if row.last_checked_at else None),
            last_verified_at=(row.last_verified_at.isoformat() if row.last_verified_at else None),
            next_recommended_check_at=(row.next_recommended_check_at.isoformat() if row.next_recommended_check_at else None),
            verified_provider_count=int(row.verified_provider_count or 0),
            warning_provider_count=int(row.warning_provider_count or 0),
            unavailable_provider_count=int(row.unavailable_provider_count or 0),
            overall_confidence=row.overall_confidence,
            badges_json=dict(row.badges_json or {}),
            updated_at=(row.updated_at.isoformat() if row.updated_at else None),
        )

    def get_summary(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
    ) -> VerificationSummaryDTO:
        tid = self._parse_target_uuid(target_id)
        summary = db.query(EntityVerificationSummary).filter(EntityVerificationSummary.target_id == tid).first()
        if summary is not None:
            return self._summary_to_dto(summary)
        # Scoped fail-safe bootstrap; no provider execution, only local recompute for this target.
        return self.recompute_verification_summary(db, target_id=tid)

    def upsert_verification_target(
        self,
        db: Session,
        *,
        payload: VerificationTargetUpsertInput | dict[str, Any],
    ) -> VerificationTargetDTO:
        data = payload if isinstance(payload, VerificationTargetUpsertInput) else VerificationTargetUpsertInput.model_validate(payload)
        now = self._now()

        subject_id = self._clean(data.subject_id, 128)
        if not subject_id:
            raise ValueError("subject_id_required")

        country_code = normalize_country_code(data.country_code)
        legal_name = normalize_legal_name(data.legal_name)
        normalized_legal_name = normalize_legal_name_key(data.legal_name)
        vat_raw, vat_norm = normalize_vat_number(data.vat_number, country_code=country_code)
        reg_raw, reg_norm = normalize_registration_number(data.registration_number)
        address_lite = normalize_address_lite(
            address_line=data.address_line,
            postal_code=data.postal_code,
            city=data.city,
            website_url=data.website_url,
        )

        row = (
            db.query(EntityVerificationTarget)
            .filter(
                EntityVerificationTarget.subject_type == data.subject_type.value,
                EntityVerificationTarget.subject_id == subject_id,
            )
            .first()
        )

        if row is None:
            row = EntityVerificationTarget(
                subject_type=data.subject_type.value,
                subject_id=subject_id,
                owner_company_id=self._clean_opt(data.owner_company_id, 64),
                global_company_id=self._parse_opt_uuid(data.global_company_id, field="global_company_id"),
                legal_name=legal_name,
                normalized_legal_name=normalized_legal_name,
                country_code=country_code,
                vat_number=vat_raw,
                vat_number_normalized=vat_norm,
                registration_number=reg_raw,
                registration_number_normalized=reg_norm,
                address_line=address_lite["address_line"],
                postal_code=address_lite["postal_code"],
                city=address_lite["city"],
                website_url=address_lite["website_url"],
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            return self._target_to_dto(row)

        row.owner_company_id = self._clean_opt(data.owner_company_id, 64)
        row.global_company_id = self._parse_opt_uuid(data.global_company_id, field="global_company_id")
        row.legal_name = legal_name
        row.normalized_legal_name = normalized_legal_name
        row.country_code = country_code
        row.vat_number = vat_raw
        row.vat_number_normalized = vat_norm
        row.registration_number = reg_raw
        row.registration_number_normalized = reg_norm
        row.address_line = address_lite["address_line"]
        row.postal_code = address_lite["postal_code"]
        row.city = address_lite["city"]
        row.website_url = address_lite["website_url"]
        row.updated_at = now
        db.add(row)
        db.flush()
        return self._target_to_dto(row)

    def acquire_inflight_check(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        provider_code: str,
        started_by_user_id: str | None = None,
        request_id: str | None = None,
        lease_ttl_seconds: int | None = None,
        recheck_cooldown_seconds: int | None = None,
        idempotency_ttl_seconds: int | None = None,
        manual_check_window_seconds: int | None = None,
        manual_check_window_max: int | None = None,
        manual_check_window_user_max: int | None = None,
    ) -> InflightAcquireResultDTO:
        tid = self._parse_target_uuid(target_id)
        provider = self._clean(provider_code, 64).upper()
        if not provider:
            raise ValueError("provider_code_required")

        now = self._now()
        lease_ttl = max(1, int(lease_ttl_seconds if lease_ttl_seconds is not None else self.inflight_ttl_seconds))
        cooldown_s = max(1, int(recheck_cooldown_seconds if recheck_cooldown_seconds is not None else self.recheck_cooldown_seconds))
        idempotency_s = max(1, int(idempotency_ttl_seconds if idempotency_ttl_seconds is not None else self.idempotency_ttl_seconds))
        manual_window_s = max(
            1,
            int(
                manual_check_window_seconds
                if manual_check_window_seconds is not None
                else self.manual_check_window_seconds
            ),
        )
        manual_window_max_count = max(
            1,
            int(
                manual_check_window_max
                if manual_check_window_max is not None
                else self.manual_check_window_max
            ),
        )
        manual_window_user_max_count = max(
            1,
            int(
                manual_check_window_user_max
                if manual_check_window_user_max is not None
                else self.manual_check_window_user_max
            ),
        )
        request = self._clean_opt(request_id, 128)
        started_by = self._clean_opt(started_by_user_id, 255)

        if started_by:
            recent_user_checks_count = (
                db.query(EntityVerificationCheck)
                .filter(
                    EntityVerificationCheck.provider_code == provider,
                    EntityVerificationCheck.created_by_user_id == started_by,
                    EntityVerificationCheck.checked_at >= (now - timedelta(seconds=manual_window_s)),
                )
                .count()
            )
            if recent_user_checks_count >= manual_window_user_max_count:
                record_segment("recheck_dedup_hit_count", 1.0)
                return InflightAcquireResultDTO(
                    acquired=False,
                    dedup_hit=True,
                    cooldown_active=True,
                    reason="manual_check_user_window_limit",
                    target_id=str(tid),
                    provider_code=provider,
                    lease_expires_at=(now + timedelta(seconds=manual_window_s)).isoformat(),
                )

        recent_checks_count = (
            db.query(EntityVerificationCheck)
            .filter(
                EntityVerificationCheck.target_id == tid,
                EntityVerificationCheck.provider_code == provider,
                EntityVerificationCheck.checked_at >= (now - timedelta(seconds=manual_window_s)),
            )
            .count()
        )
        if recent_checks_count >= manual_window_max_count:
            record_segment("recheck_dedup_hit_count", 1.0)
            return InflightAcquireResultDTO(
                acquired=False,
                dedup_hit=True,
                cooldown_active=True,
                reason="manual_check_window_limit",
                target_id=str(tid),
                provider_code=provider,
                lease_expires_at=(now + timedelta(seconds=manual_window_s)).isoformat(),
            )

        row = (
            db.query(EntityVerificationInflight)
            .filter(
                EntityVerificationInflight.target_id == tid,
                EntityVerificationInflight.provider_code == provider,
            )
            .first()
        )

        if row is not None:
            active_lease = row.lease_expires_at > now
            started_recently = row.lease_started_at >= (now - timedelta(seconds=cooldown_s))
            idempotent_hit = bool(
                request
                and row.request_id
                and request == row.request_id
                and row.lease_started_at >= (now - timedelta(seconds=idempotency_s))
            )
            if idempotent_hit:
                record_segment("recheck_dedup_hit_count", 1.0)
                return InflightAcquireResultDTO(
                    acquired=False,
                    dedup_hit=True,
                    cooldown_active=False,
                    reason="idempotency_ttl_active",
                    target_id=str(tid),
                    provider_code=provider,
                    lease_expires_at=row.lease_expires_at.isoformat(),
                )
            if started_recently:
                record_segment("recheck_dedup_hit_count", 1.0)
                return InflightAcquireResultDTO(
                    acquired=False,
                    dedup_hit=True,
                    cooldown_active=True,
                    reason="recheck_cooldown_active",
                    target_id=str(tid),
                    provider_code=provider,
                    lease_expires_at=row.lease_expires_at.isoformat(),
                )
            if active_lease:
                record_segment("recheck_dedup_hit_count", 1.0)
                return InflightAcquireResultDTO(
                    acquired=False,
                    dedup_hit=True,
                    cooldown_active=False,
                    reason="active_lease",
                    target_id=str(tid),
                    provider_code=provider,
                    lease_expires_at=row.lease_expires_at.isoformat(),
                )

            row.lease_started_at = now
            row.lease_expires_at = now + timedelta(seconds=lease_ttl)
            row.started_by_user_id = started_by
            row.request_id = request
            db.add(row)
            db.flush()
            return InflightAcquireResultDTO(
                acquired=True,
                dedup_hit=False,
                cooldown_active=False,
                reason="stale_lease_reacquired",
                target_id=str(tid),
                provider_code=provider,
                lease_expires_at=row.lease_expires_at.isoformat(),
            )

        row = EntityVerificationInflight(
            target_id=tid,
            provider_code=provider,
            lease_started_at=now,
            lease_expires_at=now + timedelta(seconds=lease_ttl),
            started_by_user_id=started_by,
            request_id=request,
        )
        db.add(row)
        db.flush()
        return InflightAcquireResultDTO(
            acquired=True,
            dedup_hit=False,
            cooldown_active=False,
            reason="lease_acquired",
            target_id=str(tid),
            provider_code=provider,
            lease_expires_at=row.lease_expires_at.isoformat(),
        )

    def release_inflight_check(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        provider_code: str,
        request_id: str | None = None,
    ) -> bool:
        tid = self._parse_target_uuid(target_id)
        provider = self._clean(provider_code, 64).upper()
        if not provider:
            raise ValueError("provider_code_required")

        row = (
            db.query(EntityVerificationInflight)
            .filter(
                EntityVerificationInflight.target_id == tid,
                EntityVerificationInflight.provider_code == provider,
            )
            .first()
        )
        if row is None:
            return False

        request = self._clean_opt(request_id, 128)
        if request and row.request_id and row.request_id != request:
            return False

        now = self._now()
        if row.lease_expires_at > now:
            row.lease_expires_at = now
            db.add(row)
            db.flush()
        return True

    def is_provider_circuit_open(self, db: Session, *, provider_code: str, at: datetime | None = None) -> bool:
        provider = self._clean(provider_code, 64).upper()
        if not provider:
            raise ValueError("provider_code_required")
        now = at or self._now()
        row = db.query(EntityVerificationProviderState).filter(EntityVerificationProviderState.provider_code == provider).first()
        if row is None or row.cooldown_until is None:
            return False
        is_open = row.cooldown_until > now
        if is_open:
            record_segment("circuit_open_count", 1.0)
        return is_open

    def _update_provider_state_after_check(
        self,
        db: Session,
        *,
        provider_code: str,
        status: ProviderStatus,
        checked_at: datetime,
    ) -> None:
        provider = self._clean(provider_code, 64).upper()
        now = checked_at
        row = db.query(EntityVerificationProviderState).filter(EntityVerificationProviderState.provider_code == provider).first()
        if row is None:
            row = EntityVerificationProviderState(
                provider_code=provider,
                window_started_at=now,
                consecutive_failure_count=0,
                cooldown_until=None,
                updated_at=now,
            )
            db.add(row)
            db.flush()

        if status == ProviderStatus.UNAVAILABLE:
            if row.window_started_at is None or (now - row.window_started_at) > timedelta(minutes=self.provider_circuit_window_minutes):
                row.window_started_at = now
                row.consecutive_failure_count = 1
            else:
                row.consecutive_failure_count = int(row.consecutive_failure_count or 0) + 1
            if int(row.consecutive_failure_count) >= int(self.provider_circuit_failure_threshold):
                row.cooldown_until = now + timedelta(seconds=self.provider_cooldown_seconds)
                record_segment("circuit_open_count", 1.0)
            row.updated_at = now
            db.add(row)
            db.flush()
            return

        row.window_started_at = now
        row.consecutive_failure_count = 0
        row.cooldown_until = None
        row.updated_at = now
        db.add(row)
        db.flush()

    def record_verification_check(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        provider_result: ProviderCheckResultDTO | dict[str, Any],
        created_by_user_id: str | None = None,
    ) -> VerificationCheckDTO:
        tid = self._parse_target_uuid(target_id)
        result = provider_result if isinstance(provider_result, ProviderCheckResultDTO) else ProviderCheckResultDTO.model_validate(provider_result)
        status = self._provider_status(result.status)
        checked_at = result.checked_at or self._now()
        evidence = self._sanitize_evidence(result.evidence_json)
        provider_code = self._clean(result.provider_code, 64).upper()
        check_type = self._clean(result.check_type, 64)
        if not provider_code:
            raise ValueError("provider_code_required")
        if not check_type:
            raise ValueError("check_type_required")

        row = EntityVerificationCheck(
            target_id=tid,
            provider_code=provider_code,
            check_type=check_type,
            status=status.value,
            match_score=result.match_score,
            provider_reference=self._clean_opt(result.provider_reference, 255),
            provider_message_code=self._clean_opt(result.provider_message_code, 128),
            provider_message_text=self._clean_opt(result.provider_message_text, 1024),
            evidence_json=evidence,
            checked_at=checked_at,
            expires_at=result.expires_at,
            created_by_user_id=self._clean_opt(created_by_user_id, 255),
        )
        db.add(row)
        db.flush()

        self._update_provider_state_after_check(
            db,
            provider_code=row.provider_code,
            status=status,
            checked_at=checked_at,
        )
        if status == ProviderStatus.UNAVAILABLE:
            record_segment("provider_unavailable_count", 1.0)

        return self._check_to_dto(row)

    def get_next_recommended_check_at(
        self,
        *,
        status: ProviderStatus | str,
        checked_at: datetime | None,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime:
        reference_now = now or self._now()
        if expires_at is not None:
            return expires_at

        started = checked_at or reference_now
        st = self._provider_status(status)
        if st == ProviderStatus.VERIFIED:
            return started + timedelta(hours=self.ttl_verified_hours)
        if st == ProviderStatus.NOT_VERIFIED:
            return started + timedelta(hours=self.ttl_not_verified_hours)
        if st == ProviderStatus.UNAVAILABLE:
            return started + timedelta(minutes=self.ttl_unavailable_minutes)
        return started + timedelta(hours=self.ttl_not_verified_hours)

    def is_check_fresh(
        self,
        *,
        status: ProviderStatus | str,
        checked_at: datetime | None,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        reference_now = now or self._now()
        next_check_at = self.get_next_recommended_check_at(
            status=status,
            checked_at=checked_at,
            expires_at=expires_at,
            now=reference_now,
        )
        return reference_now < next_check_at

    def should_refresh_check(
        self,
        *,
        status: ProviderStatus | str,
        checked_at: datetime | None,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        return not self.is_check_fresh(
            status=status,
            checked_at=checked_at,
            expires_at=expires_at,
            now=now,
        )

    def recompute_verification_summary(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        now: datetime | None = None,
    ) -> VerificationSummaryDTO:
        tid = self._parse_target_uuid(target_id)
        ref_now = now or self._now()
        checks = (
            db.query(EntityVerificationCheck)
            .filter(EntityVerificationCheck.target_id == tid)
            .order_by(EntityVerificationCheck.checked_at.desc())
            .all()
        )

        latest_by_provider: dict[str, EntityVerificationCheck] = {}
        for row in checks:
            provider = str(row.provider_code or "").strip().upper()
            if provider and provider not in latest_by_provider:
                latest_by_provider[provider] = row

        verified_count = 0
        warning_count = 0
        unavailable_count = 0
        last_checked_at: datetime | None = None
        next_recommended_candidates: list[datetime] = []
        warning_statuses = {ProviderStatus.NOT_VERIFIED.value, ProviderStatus.PARTIAL_MATCH.value}

        for row in latest_by_provider.values():
            status = str(row.status or "").strip().upper()
            if status == ProviderStatus.VERIFIED.value:
                verified_count += 1
            elif status in warning_statuses:
                warning_count += 1
            elif status == ProviderStatus.UNAVAILABLE.value:
                unavailable_count += 1
            if last_checked_at is None or row.checked_at > last_checked_at:
                last_checked_at = row.checked_at
            next_recommended_candidates.append(
                self.get_next_recommended_check_at(
                    status=status,
                    checked_at=row.checked_at,
                    expires_at=row.expires_at,
                    now=ref_now,
                )
            )

        last_verified_at = None
        for row in checks:
            if str(row.status or "").strip().upper() == ProviderStatus.VERIFIED.value:
                last_verified_at = row.checked_at
                break

        if warning_count > 0:
            overall_status = SummaryStatus.WARNING
        elif verified_count > 0:
            overall_status = SummaryStatus.GOOD
        elif unavailable_count > 0:
            overall_status = SummaryStatus.PENDING
        else:
            overall_status = SummaryStatus.UNKNOWN

        if next_recommended_candidates:
            next_recommended = min(next_recommended_candidates)
        else:
            next_recommended = ref_now

        if overall_status == SummaryStatus.GOOD:
            overall_confidence = min(0.99, 0.75 + (0.05 * float(verified_count)))
        elif overall_status == SummaryStatus.WARNING:
            overall_confidence = 0.35
        elif overall_status == SummaryStatus.PENDING:
            overall_confidence = 0.2
        else:
            overall_confidence = None

        badges_json = {
            "verified_provider_count": int(verified_count),
            "warning_provider_count": int(warning_count),
            "unavailable_provider_count": int(unavailable_count),
            "latest_provider_count": int(len(latest_by_provider)),
        }

        summary = db.query(EntityVerificationSummary).filter(EntityVerificationSummary.target_id == tid).first()
        if summary is None:
            summary = EntityVerificationSummary(target_id=tid)

        summary.overall_status = overall_status.value
        summary.last_checked_at = last_checked_at
        summary.last_verified_at = last_verified_at
        summary.next_recommended_check_at = next_recommended
        summary.verified_provider_count = int(verified_count)
        summary.warning_provider_count = int(warning_count)
        summary.unavailable_provider_count = int(unavailable_count)
        summary.overall_confidence = overall_confidence
        summary.badges_json = badges_json
        summary.updated_at = ref_now
        db.add(summary)
        db.flush()
        return self._summary_to_dto(summary)

    def process_provider_result(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        provider_result: ProviderCheckResultDTO | dict[str, Any],
        created_by_user_id: str | None = None,
        request_id: str | None = None,
        release_inflight: bool = True,
        provider_call_ms: float | None = None,
    ) -> tuple[VerificationCheckDTO, VerificationSummaryDTO]:
        """Persist provider result with scoped recompute.

        Designed for non-blocking unavailable behavior: UNAVAILABLE is recorded and mapped to PENDING summary.
        External provider calls must happen outside this method.
        """
        if provider_call_ms is not None:
            record_segment("provider_call_ms", max(0.0, float(provider_call_ms)))

        parsed_result = provider_result if isinstance(provider_result, ProviderCheckResultDTO) else ProviderCheckResultDTO.model_validate(provider_result)
        try:
            check = self.record_verification_check(
                db,
                target_id=target_id,
                provider_result=parsed_result,
                created_by_user_id=created_by_user_id,
            )
            summary = self.recompute_verification_summary(db, target_id=target_id)
            return check, summary
        finally:
            if release_inflight:
                self.release_inflight_check(
                    db,
                    target_id=target_id,
                    provider_code=parsed_result.provider_code,
                    request_id=request_id,
                )

    def _latest_check_for_provider(
        self,
        db: Session,
        *,
        target_id: uuid.UUID,
        provider_code: str,
    ) -> VerificationCheckDTO | None:
        row = (
            db.query(EntityVerificationCheck)
            .filter(
                EntityVerificationCheck.target_id == target_id,
                EntityVerificationCheck.provider_code == self._clean(provider_code, 64).upper(),
            )
            .order_by(EntityVerificationCheck.checked_at.desc())
            .first()
        )
        if row is None:
            return None
        return self._check_to_dto(row)

    def get_latest_provider_check(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        provider_code: str,
    ) -> VerificationCheckDTO | None:
        tid = self._parse_target_uuid(target_id)
        provider = self._clean(provider_code, 64).upper()
        if not provider:
            raise ValueError("provider_code_required")
        return self._latest_check_for_provider(db, target_id=tid, provider_code=provider)

    def _summary_for_target(self, db: Session, *, target_id: uuid.UUID) -> VerificationSummaryDTO | None:
        row = db.query(EntityVerificationSummary).filter(EntityVerificationSummary.target_id == target_id).first()
        if row is None:
            return None
        return self._summary_to_dto(row)

    def _build_vies_provider(
        self,
        *,
        execution_client: Any = None,
    ) -> VIESProviderAdapter:
        effective_client = execution_client
        if effective_client is None and self.vies_enabled:
            effective_client = build_default_vies_execution_client(
                wsdl_url=self.vies_wsdl_url,
                service_url=self.vies_service_url,
            )
        return VIESProviderAdapter(
            enabled=self.vies_enabled,
            execution_client=effective_client,
            connect_timeout_seconds=self.vies_connect_timeout_seconds,
            read_timeout_seconds=self.vies_read_timeout_seconds,
            total_budget_seconds=self.vies_total_budget_seconds,
            retry_count=self.vies_retry_count,
            retry_backoff_ms=self.vies_retry_backoff_ms,
        )

    def run_vies_verification_for_target(
        self,
        db: Session,
        *,
        target_id: str | uuid.UUID,
        created_by_user_id: str | None = None,
        request_id: str | None = None,
        provider: VIESProviderAdapter | None = None,
        execution_client: Any = None,
    ) -> VerificationProviderRunDTO:
        tid = self._parse_target_uuid(target_id)
        row = db.query(EntityVerificationTarget).filter(EntityVerificationTarget.id == tid).first()
        if row is None:
            raise ValueError("target_not_found")
        target = self._target_to_dto(row)

        applicability_status = get_vies_applicability_status(
            country_code=target.country_code,
            vat_number=target.vat_number_normalized or target.vat_number,
        )

        acquired = self.acquire_inflight_check(
            db,
            target_id=tid,
            provider_code="VIES",
            started_by_user_id=created_by_user_id,
            request_id=request_id,
        )
        if not acquired.acquired:
            return VerificationProviderRunDTO(
                acquired=False,
                dedup_hit=True,
                provider_called=False,
                reason=acquired.reason,
                applicability_status=applicability_status,
                check=self._latest_check_for_provider(db, target_id=tid, provider_code="VIES"),
                summary=self._summary_for_target(db, target_id=tid),
            )

        provider_adapter = provider or self._build_vies_provider(execution_client=execution_client)
        provider_called = False
        provider_call_ms: float | None = None

        if applicability_status == ViesApplicabilityStatus.VIES_NOT_APPLICABLE:
            provider_result = ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.NOT_APPLICABLE,
                checked_at=self._now(),
                provider_message_code="vies_not_applicable",
                provider_message_text="Country is outside VIES scope.",
                evidence_json={
                    "applicability_status": applicability_status.value,
                    "provider_call_skipped": True,
                    "country_code": target.country_code,
                    "vat_number_normalized": target.vat_number_normalized,
                    "request_id": request_id,
                },
            )
        elif applicability_status == ViesApplicabilityStatus.INSUFFICIENT_DATA:
            provider_result = ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.NOT_APPLICABLE,
                checked_at=self._now(),
                provider_message_code="insufficient_data",
                provider_message_text="Insufficient data for VIES applicability.",
                evidence_json={
                    "applicability_status": applicability_status.value,
                    "provider_call_skipped": True,
                    "country_code": target.country_code,
                    "vat_number_normalized": target.vat_number_normalized,
                    "request_id": request_id,
                },
            )
        elif applicability_status == ViesApplicabilityStatus.VIES_FORMAT_SUSPECT:
            provider_result = ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.PARTIAL_MATCH,
                checked_at=self._now(),
                provider_message_code="vies_format_suspect",
                provider_message_text="VAT format is suspicious for VIES; no live call performed.",
                evidence_json={
                    "applicability_status": applicability_status.value,
                    "provider_call_skipped": True,
                    "country_code": target.country_code,
                    "vat_number_normalized": target.vat_number_normalized,
                    "request_id": request_id,
                },
            )
        elif self.is_provider_circuit_open(db, provider_code="VIES"):
            provider_result = ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.UNAVAILABLE,
                checked_at=self._now(),
                expires_at=self._now() + timedelta(seconds=self.vies_cooldown_seconds),
                provider_message_code="vies_circuit_open",
                provider_message_text="VIES provider is temporarily in cooldown mode.",
                evidence_json={
                    "applicability_status": applicability_status.value,
                    "provider_raw_status": "circuit_open",
                    "country_code": target.country_code,
                    "vat_number_normalized": target.vat_number_normalized,
                    "request_id": request_id,
                },
            )
        else:
            # Ensure the external provider call does not run inside a long DB transaction.
            db.commit()
            started = time.perf_counter()
            provider_result = provider_adapter.run_check(target=target, request_id=request_id)
            provider_call_ms = (time.perf_counter() - started) * 1000.0
            provider_called = True

        check, summary = self.process_provider_result(
            db,
            target_id=tid,
            provider_result=provider_result,
            created_by_user_id=created_by_user_id,
            request_id=request_id,
            release_inflight=True,
            provider_call_ms=provider_call_ms if provider_called else None,
        )
        return VerificationProviderRunDTO(
            acquired=True,
            dedup_hit=False,
            provider_called=provider_called,
            reason="provider_result_recorded",
            applicability_status=applicability_status,
            check=check,
            summary=summary,
        )


service = EntityVerificationService()
