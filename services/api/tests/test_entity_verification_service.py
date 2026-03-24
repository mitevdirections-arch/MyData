from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import EntityVerificationCheck, EntityVerificationInflight, EntityVerificationTarget
from app.db.session import get_engine, get_session_factory
from app.modules.entity_verification.normalization import (
    is_eu_vat_eligible,
    normalize_country_code,
    normalize_legal_name,
    normalize_legal_name_key,
    normalize_registration_number,
    normalize_vat_number,
)
from app.modules.entity_verification.schemas import (
    ProviderCheckResultDTO,
    ProviderStatus,
    SummaryStatus,
    VerificationSubjectType,
    VerificationTargetUpsertInput,
)
from app.modules.entity_verification.service import EntityVerificationService


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


def _target_payload(subject_id: str) -> VerificationTargetUpsertInput:
    return VerificationTargetUpsertInput(
        subject_type=VerificationSubjectType.PARTNER,
        subject_id=subject_id,
        legal_name=" ACME Logistics  ",
        country_code="bg",
        vat_number="123456789",
        registration_number="reg-001",
        address_line=" Main street 1 ",
        postal_code=" 1000 ",
        city=" Sofia ",
        website_url="https://acme.example",
    )


def test_normalization_helpers() -> None:
    assert normalize_country_code("gr") == "EL"
    assert normalize_legal_name("  ACME  LTD ") == "ACME LTD"
    assert normalize_legal_name_key("ACME LTD") == "ACMELTD"
    vat_raw, vat_norm = normalize_vat_number(" 123 456 789 ", country_code="BG")
    assert vat_raw == "123 456 789"
    assert vat_norm == "BG123456789"
    reg_raw, reg_norm = normalize_registration_number(" reg-001 ")
    assert reg_raw == "reg-001"
    assert reg_norm == "REG001"
    assert is_eu_vat_eligible(country_code="BG", vat_number_normalized="BG123456789") is True


def test_upsert_target_create_update_no_duplicate(db) -> None:
    service = EntityVerificationService()
    subject_id = f"partner-{uuid.uuid4().hex[:10]}"

    created = service.upsert_verification_target(db, payload=_target_payload(subject_id))
    assert created.subject_id == subject_id
    assert created.country_code == "BG"
    assert created.vat_number_normalized == "BG123456789"

    updated = service.upsert_verification_target(
        db,
        payload=VerificationTargetUpsertInput(
            subject_type=VerificationSubjectType.PARTNER,
            subject_id=subject_id,
            legal_name="ACME Logistics Updated",
            country_code="BG",
            vat_number="BG123456789",
            registration_number="REG-001",
            city="Plovdiv",
        ),
    )
    assert updated.id == created.id
    assert updated.legal_name == "ACME Logistics Updated"
    assert updated.city == "Plovdiv"

    count = (
        db.query(EntityVerificationTarget)
        .filter(
            EntityVerificationTarget.subject_type == VerificationSubjectType.PARTNER.value,
            EntityVerificationTarget.subject_id == subject_id,
        )
        .count()
    )
    assert count == 1


def test_inflight_acquire_dedup_path(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )

    first = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="vies",
        started_by_user_id="tester@local",
        request_id="req-1",
    )
    assert first.acquired is True
    assert first.dedup_hit is False

    dedup_same = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="vies",
        started_by_user_id="tester@local",
        request_id="req-1",
    )
    assert dedup_same.acquired is False
    assert dedup_same.dedup_hit is True
    assert dedup_same.reason == "idempotency_ttl_active"

    released = service.release_inflight_check(
        db,
        target_id=target.id,
        provider_code="vies",
        request_id="req-1",
    )
    assert released is True

    dedup_cooldown = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="vies",
        started_by_user_id="tester@local",
        request_id="req-2",
    )
    assert dedup_cooldown.acquired is False
    assert dedup_cooldown.dedup_hit is True
    assert dedup_cooldown.cooldown_active is True


def test_inflight_manual_check_window_limit(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    now = datetime.now(timezone.utc)
    for idx in range(20):
        service.record_verification_check(
            db,
            target_id=target.id,
            provider_result=ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.NOT_VERIFIED,
                checked_at=now - timedelta(seconds=idx),
                evidence_json={"provider_raw_status": "INVALID"},
            ),
            created_by_user_id="tester@local",
        )

    blocked = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="vies",
        started_by_user_id="tester@local",
        request_id="req-window-limit",
        manual_check_window_seconds=300,
        manual_check_window_max=20,
        manual_check_window_user_max=1000,
    )
    assert blocked.acquired is False
    assert blocked.dedup_hit is True
    assert blocked.cooldown_active is True
    assert blocked.reason == "manual_check_window_limit"


def test_inflight_manual_check_user_window_limit(db) -> None:
    service = EntityVerificationService()
    actor = "abuse-user@local"
    target_a = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    target_b = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    now = datetime.now(timezone.utc)

    for idx in range(20):
        service.record_verification_check(
            db,
            target_id=target_a.id,
            provider_result=ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.NOT_VERIFIED,
                checked_at=now - timedelta(seconds=idx),
                evidence_json={"provider_raw_status": "INVALID"},
            ),
            created_by_user_id=actor,
        )

    blocked = service.acquire_inflight_check(
        db,
        target_id=target_b.id,
        provider_code="vies",
        started_by_user_id=actor,
        request_id="req-user-window-limit",
        manual_check_window_seconds=300,
        manual_check_window_user_max=20,
    )
    assert blocked.acquired is False
    assert blocked.dedup_hit is True
    assert blocked.cooldown_active is True
    assert blocked.reason == "manual_check_user_window_limit"


def test_record_check_evidence_guardrails(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )

    check = service.record_verification_check(
        db,
        target_id=target.id,
        provider_result=ProviderCheckResultDTO(
            provider_code="VIES",
            check_type="VAT",
            status=ProviderStatus.VERIFIED,
            checked_at=datetime.now(timezone.utc),
            evidence_json={
                "member_state_code": "BG",
                "vat_number_normalized": "BG123456789",
                "not_allowed_blob": "drop-me",
            },
        ),
        created_by_user_id="tester@local",
    )
    assert check.status == ProviderStatus.VERIFIED
    assert "member_state_code" in check.evidence_json
    assert "not_allowed_blob" not in check.evidence_json

    with pytest.raises(ValueError, match="evidence_payload_too_large"):
        service.record_verification_check(
            db,
            target_id=target.id,
            provider_result=ProviderCheckResultDTO(
                provider_code="VIES",
                check_type="VAT",
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(timezone.utc),
                evidence_json={
                    "provider_error_message": "x" * (17 * 1024),
                },
            ),
            created_by_user_id="tester@local",
        )


@pytest.mark.parametrize(
    ("provider_status", "expected_summary"),
    [
        (ProviderStatus.VERIFIED, SummaryStatus.GOOD),
        (ProviderStatus.NOT_VERIFIED, SummaryStatus.WARNING),
        (ProviderStatus.UNAVAILABLE, SummaryStatus.PENDING),
    ],
)
def test_recompute_summary_status_mapping(db, provider_status: ProviderStatus, expected_summary: SummaryStatus) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    service.record_verification_check(
        db,
        target_id=target.id,
        provider_result=ProviderCheckResultDTO(
            provider_code="VIES",
            check_type="VAT",
            status=provider_status,
            checked_at=datetime.now(timezone.utc),
            evidence_json={"provider_raw_status": provider_status.value},
        ),
        created_by_user_id="tester@local",
    )
    summary = service.recompute_verification_summary(db, target_id=target.id)
    assert summary.overall_status == expected_summary


def test_recompute_summary_no_checks_is_unknown(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    summary = service.recompute_verification_summary(db, target_id=target.id)
    assert summary.overall_status == SummaryStatus.UNKNOWN


def test_freshness_ttl_helpers() -> None:
    service = EntityVerificationService()
    now = datetime.now(timezone.utc)

    assert service.is_check_fresh(
        status=ProviderStatus.VERIFIED,
        checked_at=now - timedelta(hours=2),
        now=now,
    ) is True
    assert service.should_refresh_check(
        status=ProviderStatus.VERIFIED,
        checked_at=now - timedelta(hours=200),
        now=now,
    ) is True
    assert service.should_refresh_check(
        status=ProviderStatus.NOT_VERIFIED,
        checked_at=now - timedelta(hours=30),
        now=now,
    ) is True
    assert service.should_refresh_check(
        status=ProviderStatus.UNAVAILABLE,
        checked_at=now - timedelta(minutes=20),
        now=now,
    ) is True


def test_non_blocking_unavailable_process_flow(db) -> None:
    service = EntityVerificationService()
    target = service.upsert_verification_target(
        db,
        payload=_target_payload(f"partner-{uuid.uuid4().hex[:10]}"),
    )
    acquired = service.acquire_inflight_check(
        db,
        target_id=target.id,
        provider_code="VIES",
        started_by_user_id="tester@local",
        request_id="req-non-blocking",
    )
    assert acquired.acquired is True

    check, summary = service.process_provider_result(
        db,
        target_id=target.id,
        provider_result=ProviderCheckResultDTO(
            provider_code="VIES",
            check_type="VAT",
            status=ProviderStatus.UNAVAILABLE,
            checked_at=datetime.now(timezone.utc),
            evidence_json={"provider_raw_status": "UNAVAILABLE"},
        ),
        created_by_user_id="tester@local",
        request_id="req-non-blocking",
        release_inflight=True,
        provider_call_ms=12.5,
    )
    assert check.status == ProviderStatus.UNAVAILABLE
    assert summary.overall_status == SummaryStatus.PENDING

    inflight_row = (
        db.query(EntityVerificationInflight)
        .filter(
            EntityVerificationInflight.target_id == uuid.UUID(target.id),
            EntityVerificationInflight.provider_code == "VIES",
        )
        .first()
    )
    assert inflight_row is not None
    assert inflight_row.lease_expires_at <= datetime.now(timezone.utc)

    checks_count = db.query(EntityVerificationCheck).filter(EntityVerificationCheck.target_id == uuid.UUID(target.id)).count()
    assert checks_count >= 1
