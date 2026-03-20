from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid

import pytest

from app.db.session import get_engine, get_session_factory
from app.modules.entity_verification.normalization import (
    get_vies_applicability_status,
    is_country_in_vies_scope,
    is_vies_eligible,
)
from app.modules.entity_verification.providers.vies import VIESProviderAdapter
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


@pytest.fixture
def db():
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.skip("DATABASE_URL is required for entity_verification db-backed tests")
    get_engine.cache_clear()
    session = get_session_factory()()
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
