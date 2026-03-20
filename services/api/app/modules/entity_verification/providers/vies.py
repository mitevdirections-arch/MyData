from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Mapping, Protocol

from app.modules.entity_verification.normalization import (
    get_vies_applicability_status,
    normalize_country_code,
    normalize_vat_number,
)
from app.modules.entity_verification.providers.base import VerificationProviderBase
from app.modules.entity_verification.schemas import (
    ProviderCheckResultDTO,
    ProviderStatus,
    VerificationTargetDTO,
    ViesApplicabilityStatus,
)


class VIESExecutionClient(Protocol):
    def check_vat(
        self,
        *,
        country_code: str,
        vat_number: str,
        request_id: str | None = None,
        connect_timeout_seconds: int = 2,
        read_timeout_seconds: int = 4,
        total_budget_seconds: int = 7,
        retry_count: int = 1,
        retry_backoff_ms: int = 300,
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class ViesPreparedInput:
    country_code: str | None
    vat_number_raw: str | None
    vat_number_normalized: str | None
    applicability_status: ViesApplicabilityStatus


class VIESProviderAdapter(VerificationProviderBase):
    provider_code = "VIES"
    check_type = "VAT"

    def __init__(
        self,
        *,
        enabled: bool = False,
        execution_client: VIESExecutionClient | None = None,
        connect_timeout_seconds: int = 2,
        read_timeout_seconds: int = 4,
        total_budget_seconds: int = 7,
        retry_count: int = 1,
        retry_backoff_ms: int = 300,
    ) -> None:
        self.enabled = bool(enabled)
        self.execution_client = execution_client
        self.connect_timeout_seconds = max(1, int(connect_timeout_seconds))
        self.read_timeout_seconds = max(1, int(read_timeout_seconds))
        self.total_budget_seconds = max(1, int(total_budget_seconds))
        self.retry_count = max(0, int(retry_count))
        self.retry_backoff_ms = max(0, int(retry_backoff_ms))

    def evaluate_applicability(
        self,
        *,
        country_code: str | None,
        vat_number: str | None,
    ) -> ViesApplicabilityStatus:
        return get_vies_applicability_status(
            country_code=country_code,
            vat_number=vat_number,
        )

    def prepare_input(self, *, target: VerificationTargetDTO) -> ViesPreparedInput:
        country_code = target.country_code
        vat_source = target.vat_number_normalized or target.vat_number
        applicability = self.evaluate_applicability(
            country_code=country_code,
            vat_number=vat_source,
        )
        if country_code:
            country_code = normalize_country_code(country_code)
        vat_raw, vat_norm = normalize_vat_number(
            country_code=country_code,
            vat_number=vat_source,
        )
        return ViesPreparedInput(
            country_code=country_code,
            vat_number_raw=vat_raw,
            vat_number_normalized=vat_norm,
            applicability_status=applicability,
        )

    def _result_from_applicability(
        self,
        *,
        applicability: ViesApplicabilityStatus,
        prepared: ViesPreparedInput,
        request_id: str | None,
    ) -> ProviderCheckResultDTO:
        now = datetime.now(timezone.utc)
        evidence = {
            "member_state_code": prepared.country_code,
            "vat_number_normalized": prepared.vat_number_normalized,
            "provider_raw_status": applicability.value,
            "applicability_status": applicability.value,
            "provider_call_skipped": True,
            "request_id": request_id,
        }
        if applicability == ViesApplicabilityStatus.VIES_FORMAT_SUSPECT:
            return ProviderCheckResultDTO(
                provider_code=self.provider_code,
                check_type=self.check_type,
                status=ProviderStatus.PARTIAL_MATCH,
                checked_at=now,
                expires_at=now + timedelta(hours=24),
                match_score=0.25,
                provider_message_code="vies_format_suspect",
                provider_message_text="VIES applicability looks suspicious; no live provider call was made.",
                evidence_json=evidence,
            )
        return ProviderCheckResultDTO(
            provider_code=self.provider_code,
            check_type=self.check_type,
            status=ProviderStatus.NOT_APPLICABLE,
            checked_at=now,
            expires_at=now + timedelta(hours=24),
            provider_message_code=applicability.value.lower(),
            provider_message_text="VIES is not applicable for this target input.",
            evidence_json=evidence,
        )

    def _status_from_raw(self, raw: Mapping[str, Any]) -> ProviderStatus:
        status_raw = str(raw.get("status") or "").strip().upper()
        if status_raw in ProviderStatus._value2member_map_:
            return ProviderStatus(status_raw)
        if "valid" in raw:
            return ProviderStatus.VERIFIED if bool(raw.get("valid")) else ProviderStatus.NOT_VERIFIED
        return ProviderStatus.UNAVAILABLE

    def _map_execution_output(
        self,
        *,
        raw: Mapping[str, Any],
        prepared: ViesPreparedInput,
        checked_at: datetime,
        request_id: str | None,
        provider_call_ms: float,
    ) -> ProviderCheckResultDTO:
        status = self._status_from_raw(raw)
        expires_at = checked_at + (
            timedelta(days=7)
            if status == ProviderStatus.VERIFIED
            else (timedelta(hours=24) if status in {ProviderStatus.NOT_VERIFIED, ProviderStatus.PARTIAL_MATCH} else timedelta(minutes=15))
        )
        match_score_raw = raw.get("match_score")
        match_score = float(match_score_raw) if isinstance(match_score_raw, (int, float)) else None
        evidence = {
            "member_state_code": prepared.country_code,
            "vat_number_normalized": prepared.vat_number_normalized,
            "vies_valid": bool(raw.get("valid")) if "valid" in raw else None,
            "name_match_status": raw.get("name_match_status"),
            "address_match_status": raw.get("address_match_status"),
            "consultation_reference": raw.get("consultation_reference"),
            "provider_raw_status": str(raw.get("status") or status.value),
            "provider_call_ms": round(float(provider_call_ms), 3),
            "request_id": request_id,
        }
        return ProviderCheckResultDTO(
            provider_code=self.provider_code,
            check_type=self.check_type,
            status=status,
            checked_at=checked_at,
            expires_at=expires_at,
            match_score=match_score,
            provider_reference=str(raw.get("provider_reference") or "")[:255] or None,
            provider_message_code=str(raw.get("provider_message_code") or "")[:128] or None,
            provider_message_text=str(raw.get("provider_message_text") or "")[:1024] or None,
            evidence_json=evidence,
        )

    def run_check(
        self,
        *,
        target: VerificationTargetDTO,
        request_id: str | None = None,
    ) -> ProviderCheckResultDTO:
        prepared = self.prepare_input(target=target)
        applicability = prepared.applicability_status
        if applicability != ViesApplicabilityStatus.VIES_ELIGIBLE:
            return self._result_from_applicability(
                applicability=applicability,
                prepared=prepared,
                request_id=request_id,
            )

        now = datetime.now(timezone.utc)
        if not self.enabled:
            return ProviderCheckResultDTO(
                provider_code=self.provider_code,
                check_type=self.check_type,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=now,
                expires_at=now + timedelta(minutes=15),
                provider_message_code="vies_provider_disabled",
                provider_message_text="VIES provider is disabled by runtime settings.",
                evidence_json={
                    "member_state_code": prepared.country_code,
                    "vat_number_normalized": prepared.vat_number_normalized,
                    "provider_raw_status": "provider_disabled",
                    "request_id": request_id,
                },
            )

        if self.execution_client is None:
            return ProviderCheckResultDTO(
                provider_code=self.provider_code,
                check_type=self.check_type,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=now,
                expires_at=now + timedelta(minutes=15),
                provider_message_code="vies_client_missing",
                provider_message_text="VIES execution client is not configured.",
                evidence_json={
                    "member_state_code": prepared.country_code,
                    "vat_number_normalized": prepared.vat_number_normalized,
                    "provider_raw_status": "client_missing",
                    "request_id": request_id,
                },
            )

        started = time.perf_counter()
        try:
            raw = self.execution_client.check_vat(
                country_code=str(prepared.country_code),
                vat_number=str(prepared.vat_number_normalized),
                request_id=request_id,
                connect_timeout_seconds=self.connect_timeout_seconds,
                read_timeout_seconds=self.read_timeout_seconds,
                total_budget_seconds=self.total_budget_seconds,
                retry_count=self.retry_count,
                retry_backoff_ms=self.retry_backoff_ms,
            )
            call_ms = (time.perf_counter() - started) * 1000.0
            return self._map_execution_output(
                raw=dict(raw or {}),
                prepared=prepared,
                checked_at=datetime.now(timezone.utc),
                request_id=request_id,
                provider_call_ms=call_ms,
            )
        except Exception as exc:  # noqa: BLE001
            call_ms = (time.perf_counter() - started) * 1000.0
            return ProviderCheckResultDTO(
                provider_code=self.provider_code,
                check_type=self.check_type,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
                provider_message_code="vies_execution_error",
                provider_message_text=str(exc)[:1024],
                evidence_json={
                    "member_state_code": prepared.country_code,
                    "vat_number_normalized": prepared.vat_number_normalized,
                    "provider_error_message": str(exc)[:1024],
                    "provider_raw_status": "execution_error",
                    "provider_call_ms": round(float(call_ms), 3),
                    "request_id": request_id,
                },
            )

