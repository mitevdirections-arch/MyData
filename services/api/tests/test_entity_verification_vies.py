from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

import pytest
import sqlalchemy as sa

from app.db.session import get_engine, get_session_factory
from app.modules.entity_verification.normalization import (
    get_vies_applicability_status,
    is_country_in_vies_scope,
    is_vies_eligible,
)
from app.modules.entity_verification.providers.vies import VIESProviderAdapter, ViesSoapExecutionClient
from app.modules.entity_verification.schemas import (
    ProviderStatus,
    SummaryStatus,
    VerificationSubjectType,
    VerificationTargetDTO,
    VerificationTargetUpsertInput,
    ViesApplicabilityStatus,
)
from app.modules.entity_verification.service import EntityVerificationService


class _CountingClient:
    def __init__(self, *, response: dict | None = None) -> None:
        self.calls = 0
        self.response = response or {"valid": True, "status": "VERIFIED"}

    def check_vat(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        return dict(self.response)


class _RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def check_vat(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        raise self.exc


class _SequenceTransport:
    def __init__(self, events: list[bytes | Exception]) -> None:
        self.events = list(events)
        self.calls = 0

    def post_xml(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        idx = min(self.calls - 1, len(self.events) - 1)
        item = self.events[idx]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def db():
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL is required for entity_verification db-backed tests")
    get_engine.cache_clear()
    session = None
    try:
        session = get_session_factory()()
        session.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        if session is not None:
            session.close()
        get_engine.cache_clear()
        pytest.skip(f"entity_verification db unavailable: {exc.__class__.__name__}")
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        get_engine.cache_clear()


def _target(subject_id: str, *, country_code: str, vat_number: str | None) -> VerificationTargetUpsertInput:
    return VerificationTargetUpsertInput(
        subject_type=VerificationSubjectType.PARTNER,
        subject_id=subject_id,
        legal_name="Verifier VIES Test",
        country_code=country_code,
        vat_number=vat_number,
        registration_number=None,
    )


def _soap_response_xml(*, valid: bool) -> bytes:
    is_valid = "true" if valid else "false"
    return (
        "<soap:Envelope xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\">"
        "<soap:Body>"
        "<checkVatResponse xmlns=\"urn:ec.europa.eu:taxud:vies:services:checkVat:types\">"
        "<countryCode>BG</countryCode>"
        "<vatNumber>123456789</vatNumber>"
        "<requestDate>2026-03-20+00:00</requestDate>"
        f"<valid>{is_valid}</valid>"
        "<name>ACME LTD</name>"
        "<address>Sofia</address>"
        "</checkVatResponse>"
        "</soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")


def _soap_fault_xml(*, fault_code: str, fault_string: str) -> bytes:
    return (
        "<soap:Envelope xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\">"
        "<soap:Body>"
        "<soap:Fault>"
        f"<faultcode>{fault_code}</faultcode>"
        f"<faultstring>{fault_string}</faultstring>"
        "</soap:Fault>"
        "</soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")


def test_vies_scope_eligibility() -> None:
    assert get_vies_applicability_status(country_code="BG", vat_number="BG123456789") == ViesApplicabilityStatus.VIES_ELIGIBLE
    assert is_vies_eligible(country_code="BG", vat_number="123456789") is True


def test_vies_xi_handling() -> None:
    assert is_country_in_vies_scope("XI") is True
    assert get_vies_applicability_status(country_code="XI", vat_number="XI123456789") == ViesApplicabilityStatus.VIES_ELIGIBLE


def test_vies_not_applicable_country() -> None:
    assert get_vies_applicability_status(country_code="US", vat_number="US123456789") == ViesApplicabilityStatus.VIES_NOT_APPLICABLE


def test_vies_insufficient_data() -> None:
    assert get_vies_applicability_status(country_code="BG", vat_number=None) == ViesApplicabilityStatus.INSUFFICIENT_DATA


def test_vies_format_suspect() -> None:
    assert get_vies_applicability_status(country_code="BG", vat_number="FR123456789") == ViesApplicabilityStatus.VIES_FORMAT_SUSPECT


def test_vies_provider_safe_unavailable_path() -> None:
    adapter = VIESProviderAdapter(enabled=True, execution_client=None)
    target = VerificationTargetDTO(
        id=str(uuid.uuid4()),
        subject_type=VerificationSubjectType.PARTNER,
        subject_id="subject-a",
        legal_name="Name",
        normalized_legal_name="NAME",
        country_code="BG",
        vat_number="BG123456789",
        vat_number_normalized="BG123456789",
        registration_number=None,
        registration_number_normalized=None,
        address_line=None,
        postal_code=None,
        city=None,
        website_url=None,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    result = adapter.run_check(target=target, request_id="req-1")
    assert result.status == ProviderStatus.UNAVAILABLE


def test_vies_live_client_success_mapping() -> None:
    transport = _SequenceTransport([_soap_response_xml(valid=True)])
    client = ViesSoapExecutionClient(transport=transport)
    out = client.check_vat(
        country_code="BG",
        vat_number="123456789",
        request_id="req-success",
        retry_count=0,
    )
    assert out["status"] == "VERIFIED"
    assert out["valid"] is True
    assert out.get("provider_reference") is not None
    assert out.get("source") == "official_vies_soap"
    assert transport.calls == 1


def test_vies_live_client_invalid_mapping() -> None:
    transport = _SequenceTransport([_soap_response_xml(valid=False)])
    client = ViesSoapExecutionClient(transport=transport)
    out = client.check_vat(
        country_code="BG",
        vat_number="123456789",
        request_id="req-invalid",
        retry_count=0,
    )
    assert out["status"] == "NOT_VERIFIED"
    assert out["valid"] is False


def test_vies_live_client_fault_unavailable_mapping() -> None:
    transport = _SequenceTransport([_soap_fault_xml(fault_code="SERVICE_UNAVAILABLE", fault_string="SERVICE_UNAVAILABLE")])
    client = ViesSoapExecutionClient(transport=transport)
    out = client.check_vat(
        country_code="BG",
        vat_number="123456789",
        request_id="req-unavailable",
        retry_count=0,
    )
    assert out["status"] == "UNAVAILABLE"


def test_vies_live_client_fault_not_verified_mapping() -> None:
    transport = _SequenceTransport([_soap_fault_xml(fault_code="INVALID_INPUT", fault_string="INVALID_INPUT")])
    client = ViesSoapExecutionClient(transport=transport)
    out = client.check_vat(
        country_code="BG",
        vat_number="123456789",
        request_id="req-fault-invalid",
        retry_count=0,
    )
    assert out["status"] == "NOT_VERIFIED"


def test_vies_live_client_retries_once_then_success() -> None:
    transport = _SequenceTransport([TimeoutError("TIMEOUT"), _soap_response_xml(valid=True)])
    client = ViesSoapExecutionClient(transport=transport, sleep_fn=lambda _v: None)
    out = client.check_vat(
        country_code="BG",
        vat_number="123456789",
        request_id="req-retry",
        retry_count=1,
        retry_backoff_ms=1,
    )
    assert out["status"] == "VERIFIED"
    assert transport.calls == 2


def test_service_no_provider_call_when_not_applicable(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="US",
            vat_number="US123456789",
        ),
    )
    client = _CountingClient()
    provider = VIESProviderAdapter(enabled=True, execution_client=client)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-not-applicable",
        provider=provider,
    )
    assert out.provider_called is False
    assert client.calls == 0
    assert out.check is not None
    assert out.check.status == ProviderStatus.NOT_APPLICABLE
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.UNKNOWN


def test_service_no_provider_call_when_format_suspect(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="FR123456789",
        ),
    )
    client = _CountingClient()
    provider = VIESProviderAdapter(enabled=True, execution_client=client)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-format-suspect",
        provider=provider,
    )
    assert out.provider_called is False
    assert client.calls == 0
    assert out.check is not None
    assert out.check.status == ProviderStatus.PARTIAL_MATCH
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.WARNING


def test_service_disabled_live_vies_returns_unavailable_non_blocking(db) -> None:
    service = EntityVerificationService()
    service.vies_enabled = False
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    client = _CountingClient()
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-disabled",
        execution_client=client,
    )
    assert out.check is not None
    assert out.check.status == ProviderStatus.UNAVAILABLE
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.PENDING
    assert client.calls == 0


def test_service_eligible_success_verified_mapping(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    client = _CountingClient(
        response={
            "status": "VERIFIED",
            "valid": True,
            "consultation_reference": "CONS-123",
            "provider_reference": "CONS-123",
            "provider_message_code": "vies_valid",
            "provider_message_text": "ok",
            "source": "official_vies_soap",
            "provider_payload_version": "vies_check_vat_v1",
            "unknown_blob": "must_not_be_stored",
        }
    )
    provider = VIESProviderAdapter(enabled=True, execution_client=client)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-success-map",
        provider=provider,
    )
    assert out.provider_called is True
    assert client.calls == 1
    assert out.check is not None
    assert out.check.status == ProviderStatus.VERIFIED
    assert out.check.provider_reference == "CONS-123"
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.GOOD
    assert "unknown_blob" not in (out.check.evidence_json or {})


def test_service_eligible_invalid_not_verified_mapping(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    client = _CountingClient(response={"status": "NOT_VERIFIED", "valid": False})
    provider = VIESProviderAdapter(enabled=True, execution_client=client)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-invalid-map",
        provider=provider,
    )
    assert out.check is not None
    assert out.check.status == ProviderStatus.NOT_VERIFIED
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.WARNING


def test_service_eligible_client_error_maps_unavailable(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    provider = VIESProviderAdapter(enabled=True, execution_client=_RaisingClient(TimeoutError("timeout")))
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-timeout-map",
        provider=provider,
    )
    assert out.check is not None
    assert out.check.status == ProviderStatus.UNAVAILABLE
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.PENDING


def test_summary_mapping_on_unavailable(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    provider = VIESProviderAdapter(enabled=True, execution_client=None)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="req-unavailable",
        provider=provider,
    )
    assert out.check is not None
    assert out.check.status == ProviderStatus.UNAVAILABLE
    assert out.summary is not None
    assert out.summary.overall_status == SummaryStatus.PENDING


def test_inflight_dedup_preserved_during_vies_execution(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target(
            f"partner-{uuid.uuid4().hex[:10]}",
            country_code="BG",
            vat_number="BG123456789",
        ),
    )
    first = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="VIES",
        started_by_user_id="tester@local",
        request_id="lock-1",
    )
    assert first.acquired is True

    client = _CountingClient()
    provider = VIESProviderAdapter(enabled=True, execution_client=client)
    out = service.run_vies_verification_for_target(
        db,
        target_id=target.id,
        created_by_user_id="tester@local",
        request_id="lock-2",
        provider=provider,
    )
    assert out.acquired is False
    assert out.dedup_hit is True
    assert out.provider_called is False
    assert client.calls == 0
