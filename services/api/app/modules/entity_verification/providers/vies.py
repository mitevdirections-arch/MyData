from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import http.client
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree
from xml.sax.saxutils import escape

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


VIES_OFFICIAL_WSDL_URL = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"
VIES_OFFICIAL_SERVICE_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
VIES_SOAP_ACTION = '""'
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
VIES_NS = "urn:ec.europa.eu:taxud:vies:services:checkVat:types"

UNAVAILABLE_FAULT_CODES = {
    "SERVICE_UNAVAILABLE",
    "MS_UNAVAILABLE",
    "TIMEOUT",
    "SERVER_BUSY",
    "GLOBAL_MAX_CONCURRENT_REQ",
}
NOT_VERIFIED_FAULT_CODES = {
    "INVALID_INPUT",
    "INVALID_REQUESTER_INFO",
    "INVALID_REQUESTER",
    "VAT_BLOCKED",
}


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


class VIESHTTPTransport(Protocol):
    def post_xml(
        self,
        *,
        endpoint_url: str,
        payload: bytes,
        soap_action: str,
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        total_timeout_seconds: float,
    ) -> bytes:
        ...


class HTTPClientViesTransport:
    def post_xml(
        self,
        *,
        endpoint_url: str,
        payload: bytes,
        soap_action: str,
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        total_timeout_seconds: float,
    ) -> bytes:
        parsed = urlparse(endpoint_url)
        scheme = str(parsed.scheme or "").strip().lower()
        if scheme not in {"https", "http"}:
            raise ValueError("vies_endpoint_scheme_not_supported")
        host = str(parsed.hostname or "").strip()
        if not host:
            raise ValueError("vies_endpoint_host_missing")
        port = int(parsed.port or (443 if scheme == "https" else 80))
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        connection_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = connection_cls(host, port, timeout=max(0.1, float(connect_timeout_seconds)))
        started = time.perf_counter()
        try:
            conn.request(
                "POST",
                path,
                body=payload,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "Accept": "text/xml",
                    "SOAPAction": soap_action,
                    "User-Agent": "mydata-verifier-vies/1.0",
                },
            )
            response = conn.getresponse()
            elapsed = time.perf_counter() - started
            remaining = max(0.1, float(total_timeout_seconds) - elapsed)
            read_timeout = max(0.1, min(float(read_timeout_seconds), remaining))
            sock = getattr(conn, "sock", None)
            if sock is not None:
                sock.settimeout(read_timeout)
            body = response.read()
            if response.status >= 400 and not body:
                raise RuntimeError(f"vies_http_status_{response.status}")
            return body
        finally:
            conn.close()


@dataclass(frozen=True)
class ViesPreparedInput:
    country_code: str | None
    vat_number_raw: str | None
    vat_number_normalized: str | None
    applicability_status: ViesApplicabilityStatus


def _xml_find_text(element: ElementTree.Element, names: list[str]) -> str | None:
    for name in names:
        node = element.find(name)
        if node is None:
            continue
        text = str(node.text or "").strip()
        if text:
            return text
    return None


def _clean_vat_digits(vat_number: str) -> str:
    return "".join(ch for ch in str(vat_number or "").upper() if ch.isalnum())


class ViesSoapExecutionClient:
    def __init__(
        self,
        *,
        wsdl_url: str = VIES_OFFICIAL_WSDL_URL,
        service_url: str = VIES_OFFICIAL_SERVICE_URL,
        transport: VIESHTTPTransport | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.wsdl_url = str(wsdl_url or VIES_OFFICIAL_WSDL_URL).strip() or VIES_OFFICIAL_WSDL_URL
        self.service_url = str(service_url or VIES_OFFICIAL_SERVICE_URL).strip() or VIES_OFFICIAL_SERVICE_URL
        self.transport = transport or HTTPClientViesTransport()
        self.sleep_fn = sleep_fn or time.sleep

    def _is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, OSError, http.client.HTTPException)):
            return True
        msg = str(exc or "").upper()
        return (
            "VIES_HTTP_STATUS_5" in msg
            or "VIES_HTTP_STATUS_429" in msg
            or any(code in msg for code in UNAVAILABLE_FAULT_CODES)
        )

    def _build_check_vat_envelope(self, *, country_code: str, vat_number: str) -> bytes:
        payload = (
            f"<soapenv:Envelope xmlns:soapenv=\"{SOAP_NS}\" xmlns:tns=\"{VIES_NS}\">"
            "<soapenv:Header/>"
            "<soapenv:Body>"
            "<tns:checkVat>"
            f"<tns:countryCode>{escape(country_code)}</tns:countryCode>"
            f"<tns:vatNumber>{escape(vat_number)}</tns:vatNumber>"
            "</tns:checkVat>"
            "</soapenv:Body>"
            "</soapenv:Envelope>"
        )
        return payload.encode("utf-8")

    def _parse_fault(self, fault: ElementTree.Element) -> Mapping[str, Any]:
        fault_string = _xml_find_text(
            fault,
            [
                "faultstring",
                f"{{{SOAP_NS}}}faultstring",
            ],
        ) or "VIES fault"
        fault_code = _xml_find_text(
            fault,
            [
                "faultcode",
                f"{{{SOAP_NS}}}faultcode",
            ],
        )
        normalized = ""
        candidate_tokens: list[str] = []
        for source in (fault_code, fault_string):
            raw = str(source or "").strip().upper().replace("-", "_")
            if not raw:
                continue
            token = raw.split(":", 1)[-1].split(" ", 1)[0]
            if not token:
                continue
            candidate_tokens.append(token)
            if token in NOT_VERIFIED_FAULT_CODES or token in UNAVAILABLE_FAULT_CODES:
                normalized = token
                break
        if not normalized:
            normalized = candidate_tokens[0] if candidate_tokens else "FAULT"
        if normalized in NOT_VERIFIED_FAULT_CODES:
            status = "NOT_VERIFIED"
        elif normalized in UNAVAILABLE_FAULT_CODES:
            status = "UNAVAILABLE"
        else:
            status = "UNAVAILABLE"
        return {
            "status": status,
            "provider_message_code": f"vies_fault_{normalized.lower()}"[:128],
            "provider_message_text": fault_string[:1024],
            "provider_raw_status": normalized or "FAULT",
            "provider_error_code": normalized or None,
        }

    def _parse_response(self, payload: bytes) -> Mapping[str, Any]:
        root = ElementTree.fromstring(payload)
        body = root.find(f".//{{{SOAP_NS}}}Body")
        if body is None:
            raise ValueError("vies_response_body_missing")

        fault = body.find(f"{{{SOAP_NS}}}Fault")
        if fault is not None:
            return self._parse_fault(fault)

        response = body.find(f".//{{{VIES_NS}}}checkVatResponse")
        if response is None:
            response = body.find(".//checkVatResponse")
        if response is None:
            raise ValueError("vies_response_missing_checkVatResponse")

        valid_raw = _xml_find_text(response, [f"{{{VIES_NS}}}valid", "valid"]) or "false"
        valid = valid_raw.strip().lower() == "true"
        request_identifier = _xml_find_text(
            response,
            [
                f"{{{VIES_NS}}}requestIdentifier",
                "requestIdentifier",
                f"{{{VIES_NS}}}requestDate",
                "requestDate",
            ],
        )
        name_raw = _xml_find_text(response, [f"{{{VIES_NS}}}name", "name"])
        addr_raw = _xml_find_text(response, [f"{{{VIES_NS}}}address", "address"])
        name_norm = str(name_raw or "").strip()
        addr_norm = str(addr_raw or "").strip()
        return {
            "status": "VERIFIED" if valid else "NOT_VERIFIED",
            "valid": valid,
            "provider_reference": request_identifier,
            "consultation_reference": request_identifier,
            "provider_message_code": "vies_valid" if valid else "vies_not_verified",
            "provider_message_text": (
                "VIES confirmed active VAT registration." if valid else "VIES did not confirm VAT registration."
            ),
            "provider_raw_status": "VALID" if valid else "INVALID",
            "name_match_status": None if not name_norm or name_norm == "---" else "AVAILABLE",
            "address_match_status": None if not addr_norm or addr_norm == "---" else "AVAILABLE",
        }

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
        cc = normalize_country_code(country_code)
        vat = _clean_vat_digits(vat_number)
        if not cc or not vat:
            raise ValueError("vies_input_invalid")

        attempts = max(1, int(retry_count) + 1)
        started = time.perf_counter()
        last_exc: Exception | None = None
        for idx in range(attempts):
            elapsed = time.perf_counter() - started
            remaining = float(total_budget_seconds) - elapsed
            if remaining <= 0:
                raise TimeoutError("vies_total_budget_exceeded")
            try:
                envelope = self._build_check_vat_envelope(country_code=cc, vat_number=vat)
                raw = self.transport.post_xml(
                    endpoint_url=self.service_url,
                    payload=envelope,
                    soap_action=VIES_SOAP_ACTION,
                    connect_timeout_seconds=max(1, int(connect_timeout_seconds)),
                    read_timeout_seconds=max(1, int(read_timeout_seconds)),
                    total_timeout_seconds=max(0.1, remaining),
                )
                parsed = dict(self._parse_response(raw))
                parsed["request_id"] = request_id
                parsed["source"] = "official_vies_soap"
                parsed["provider_payload_version"] = "vies_check_vat_v1"
                return parsed
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                is_last = idx >= (attempts - 1)
                if is_last or not self._is_retryable_error(exc):
                    raise
                elapsed_retry = time.perf_counter() - started
                remaining_retry = float(total_budget_seconds) - elapsed_retry
                if remaining_retry <= 0:
                    raise
                backoff_seconds = min(max(0.0, float(retry_backoff_ms) / 1000.0), max(0.0, remaining_retry - 0.05))
                if backoff_seconds > 0:
                    self.sleep_fn(backoff_seconds)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("vies_execution_unknown_failure")


def build_default_vies_execution_client(
    *,
    wsdl_url: str | None = None,
    service_url: str | None = None,
    transport: VIESHTTPTransport | None = None,
) -> ViesSoapExecutionClient:
    return ViesSoapExecutionClient(
        wsdl_url=wsdl_url or VIES_OFFICIAL_WSDL_URL,
        service_url=service_url or VIES_OFFICIAL_SERVICE_URL,
        transport=transport,
    )


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

    def _vat_for_provider_call(self, prepared: ViesPreparedInput) -> str:
        vat_norm = str(prepared.vat_number_normalized or "").strip().upper()
        country = str(prepared.country_code or "").strip().upper()
        if country and vat_norm.startswith(country):
            return vat_norm[len(country) :]
        return vat_norm

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
            "source": raw.get("source"),
            "provider_payload_version": raw.get("provider_payload_version"),
        }
        return ProviderCheckResultDTO(
            provider_code=self.provider_code,
            check_type=self.check_type,
            status=status,
            checked_at=checked_at,
            expires_at=expires_at,
            match_score=match_score,
            provider_reference=str(raw.get("provider_reference") or raw.get("consultation_reference") or "")[:255] or None,
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
                    "source": "official_vies_soap",
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
                    "source": "official_vies_soap",
                },
            )

        started = time.perf_counter()
        try:
            raw = self.execution_client.check_vat(
                country_code=str(prepared.country_code),
                vat_number=self._vat_for_provider_call(prepared),
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
                    "source": "official_vies_soap",
                },
            )
