from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
import app.modules.partners.router as partners_router
from app.modules.entity_verification.schemas import (
    ProviderStatus,
    SummaryStatus,
    VerificationCheckDTO,
    VerificationProviderRunDTO,
    VerificationSummaryDTO,
    VerificationSubjectType,
    VerificationTargetDTO,
    ViesApplicabilityStatus,
)


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


def _auth_headers() -> dict[str, str]:
    tok = create_access_token({"sub": "superadmin@ops.local", "roles": ["SUPERADMIN"], "tenant_id": "platform"})
    return {"Authorization": f"Bearer {tok}"}


def _target_dto(target_id: str | None = None) -> VerificationTargetDTO:
    tid = target_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return VerificationTargetDTO(
        id=tid,
        subject_type=VerificationSubjectType.PARTNER,
        subject_id="partner-001",
        owner_company_id="tenant-001",
        global_company_id=None,
        legal_name="Smoke Partner Ltd",
        normalized_legal_name="SMOKEPARTNERLTD",
        country_code="BG",
        vat_number="BG123456789",
        vat_number_normalized="BG123456789",
        registration_number="REG001",
        registration_number_normalized="REG001",
        address_line="Main 1",
        postal_code="1000",
        city="Sofia",
        website_url="https://partner.example",
        created_at=now,
        updated_at=now,
    )


def _summary_dto(target_id: str, *, status: SummaryStatus = SummaryStatus.PENDING) -> VerificationSummaryDTO:
    now = datetime.now(timezone.utc).isoformat()
    return VerificationSummaryDTO(
        target_id=target_id,
        overall_status=status,
        last_checked_at=now,
        last_verified_at=None,
        next_recommended_check_at=now,
        verified_provider_count=0,
        warning_provider_count=0,
        unavailable_provider_count=1,
        overall_confidence=0.2,
        badges_json={},
        updated_at=now,
    )


def _check_dto(target_id: str, *, status: ProviderStatus = ProviderStatus.UNAVAILABLE) -> VerificationCheckDTO:
    now = datetime.now(timezone.utc).isoformat()
    return VerificationCheckDTO(
        id=str(uuid.uuid4()),
        target_id=target_id,
        provider_code="VIES",
        check_type="VAT",
        status=status,
        checked_at=now,
        expires_at=None,
        match_score=None,
        provider_reference=None,
        provider_message_code="provider_unavailable",
        provider_message_text="provider unavailable",
        evidence_json={"applicability_status": "VIES_ELIGIBLE"},
        created_by_user_id="superadmin@ops.local",
    )


def test_partner_verification_hooks_openapi_paths_exist() -> None:
    paths = app.openapi().get("paths") or {}
    assert "/admin/partners/{partner_id}/verification-summary" in paths
    assert "/admin/partners/{partner_id}/verification/recheck" in paths
    assert "get" in paths["/admin/partners/{partner_id}/verification-summary"]
    assert "post" in paths["/admin/partners/{partner_id}/verification/recheck"]


def test_partner_summary_route_no_provider_call(monkeypatch) -> None:
    fake_db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    headers = _auth_headers()
    target = _target_dto()
    summary = _summary_dto(target.id)
    check = _check_dto(target.id)

    monkeypatch.setattr(partners_router.service, "resolve_partner_verification_target", lambda _db, company_id, partner_id: target)
    monkeypatch.setattr(partners_router.verification_service, "get_summary", lambda _db, target_id: summary)
    monkeypatch.setattr(partners_router.verification_service, "get_latest_provider_check", lambda _db, target_id, provider_code: check)

    called = SimpleNamespace(value=False)

    def _should_not_call(*_args, **_kwargs):
        called.value = True
        raise AssertionError("provider_call_must_not_happen_on_summary_read")

    monkeypatch.setattr(partners_router.verification_service, "run_vies_verification_for_target", _should_not_call)

    try:
        client = TestClient(app)
        resp = client.get("/admin/partners/partner-001/verification-summary", headers=headers)
        assert resp.status_code == 200
        payload = (resp.json() or {}).get("result") or {}
        assert payload.get("partner_id") == "partner-001"
        assert payload.get("target_id") == target.id
        assert payload.get("provider_status") == "UNAVAILABLE"
        assert payload.get("applicability_status") == "VIES_ELIGIBLE"
        assert payload.get("non_blocking") is True
        assert called.value is False
    finally:
        app.dependency_overrides.clear()


def test_partner_recheck_route_resolves_target_and_non_blocking(monkeypatch) -> None:
    fake_db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    headers = _auth_headers()
    target = _target_dto()
    summary = _summary_dto(target.id, status=SummaryStatus.PENDING)
    check = _check_dto(target.id, status=ProviderStatus.UNAVAILABLE)
    calls = SimpleNamespace(resolver=0, run_target_id=None)

    def _resolve(_db, company_id, partner_id):
        calls.resolver += 1
        return target

    def _run_vies(_db, **kwargs):
        calls.run_target_id = kwargs.get("target_id")
        return VerificationProviderRunDTO(
            acquired=True,
            dedup_hit=False,
            provider_called=False,
            reason="provider_result_recorded",
            applicability_status=ViesApplicabilityStatus.VIES_ELIGIBLE,
            check=check,
            summary=summary,
        )

    monkeypatch.setattr(partners_router.service, "resolve_partner_verification_target", _resolve)
    monkeypatch.setattr(partners_router.verification_service, "run_vies_verification_for_target", _run_vies)

    try:
        client = TestClient(app)
        resp = client.post(
            "/admin/partners/partner-001/verification/recheck",
            headers=headers,
            json={"provider_code": "VIES", "request_id": "req-1"},
        )
        assert resp.status_code == 200
        body = resp.json() or {}
        result = body.get("result") or {}
        assert result.get("partner_id") == "partner-001"
        assert result.get("target_id") == target.id
        assert result.get("overall_status") == "PENDING"
        assert result.get("provider_status") == "UNAVAILABLE"
        assert result.get("applicability_status") == "VIES_ELIGIBLE"
        assert result.get("provider_code") == "VIES"
        assert result.get("non_blocking") is True
        assert body.get("acquired") is True
        assert body.get("dedup_hit") is False
        assert body.get("provider_called") is False
        assert calls.resolver == 1
        assert calls.run_target_id == target.id
    finally:
        app.dependency_overrides.clear()


def test_partner_target_is_reused_across_summary_and_recheck(monkeypatch) -> None:
    fake_db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    headers = _auth_headers()
    fixed_target = _target_dto(str(uuid.uuid4()))
    summary = _summary_dto(fixed_target.id, status=SummaryStatus.UNKNOWN)
    check = _check_dto(fixed_target.id, status=ProviderStatus.NOT_APPLICABLE)
    resolver_calls = SimpleNamespace(count=0)

    def _resolve(_db, company_id, partner_id):
        resolver_calls.count += 1
        return fixed_target

    monkeypatch.setattr(partners_router.service, "resolve_partner_verification_target", _resolve)
    monkeypatch.setattr(partners_router.verification_service, "get_summary", lambda _db, target_id: summary)
    monkeypatch.setattr(partners_router.verification_service, "get_latest_provider_check", lambda _db, target_id, provider_code: check)
    monkeypatch.setattr(
        partners_router.verification_service,
        "run_vies_verification_for_target",
        lambda _db, **_kwargs: VerificationProviderRunDTO(
            acquired=False,
            dedup_hit=True,
            provider_called=False,
            reason="active_lease",
            applicability_status=ViesApplicabilityStatus.VIES_NOT_APPLICABLE,
            check=check,
            summary=summary,
        ),
    )

    try:
        client = TestClient(app)
        summary_resp = client.get("/admin/partners/partner-001/verification-summary", headers=headers)
        recheck_resp = client.post(
            "/admin/partners/partner-001/verification/recheck",
            headers=headers,
            json={"provider_code": "VIES", "request_id": "req-2"},
        )
        assert summary_resp.status_code == 200
        assert recheck_resp.status_code == 200
        summary_target = ((summary_resp.json() or {}).get("result") or {}).get("target_id")
        recheck_target = ((recheck_resp.json() or {}).get("result") or {}).get("target_id")
        assert summary_target == fixed_target.id
        assert recheck_target == fixed_target.id
        assert resolver_calls.count == 2
    finally:
        app.dependency_overrides.clear()
