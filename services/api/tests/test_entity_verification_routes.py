from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
import app.modules.entity_verification.router as ev_router
from app.modules.entity_verification.schemas import (
    ProviderStatus,
    SummaryStatus,
    VerificationCheckDTO,
    VerificationProviderRunDTO,
    VerificationSummaryDTO,
    VerificationTargetDTO,
    VerificationSubjectType,
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
        legal_name="ACME",
        normalized_legal_name="ACME",
        country_code="BG",
        vat_number="BG123456789",
        vat_number_normalized="BG123456789",
        registration_number="REG001",
        registration_number_normalized="REG001",
        address_line="Main 1",
        postal_code="1000",
        city="Sofia",
        website_url="https://acme.example",
        created_at=now,
        updated_at=now,
    )


def _summary_dto(target_id: str) -> VerificationSummaryDTO:
    now = datetime.now(timezone.utc).isoformat()
    return VerificationSummaryDTO(
        target_id=target_id,
        overall_status=SummaryStatus.UNKNOWN,
        last_checked_at=now,
        last_verified_at=None,
        next_recommended_check_at=now,
        verified_provider_count=0,
        warning_provider_count=0,
        unavailable_provider_count=0,
        overall_confidence=None,
        badges_json={},
        updated_at=now,
    )


def _check_dto(target_id: str) -> VerificationCheckDTO:
    now = datetime.now(timezone.utc).isoformat()
    return VerificationCheckDTO(
        id=str(uuid.uuid4()),
        target_id=target_id,
        provider_code="VIES",
        check_type="VAT",
        status=ProviderStatus.NOT_APPLICABLE,
        checked_at=now,
        expires_at=None,
        match_score=None,
        provider_reference=None,
        provider_message_code="vies_not_applicable",
        provider_message_text="not applicable",
        evidence_json={"applicability_status": "VIES_NOT_APPLICABLE", "provider_raw_status": "VIES_NOT_APPLICABLE"},
        created_by_user_id="superadmin@ops.local",
    )


def test_entity_verification_openapi_paths_exist() -> None:
    schema = app.openapi()
    paths = schema.get("paths") or {}
    assert "/admin/entity-verification/targets/upsert" in paths
    assert "/admin/entity-verification/targets/{target_id}" in paths
    assert "/admin/entity-verification/targets/{target_id}/summary" in paths
    assert "/admin/entity-verification/targets/{target_id}/checks" in paths
    assert "/admin/entity-verification/targets/{target_id}/recheck" in paths
    assert "/admin/entity-verification/targets/{target_id}/providers/vies/check" in paths
    assert "post" in paths["/admin/entity-verification/targets/upsert"]
    assert "get" in paths["/admin/entity-verification/targets/{target_id}"]
    assert "get" in paths["/admin/entity-verification/targets/{target_id}/summary"]
    assert "get" in paths["/admin/entity-verification/targets/{target_id}/checks"]
    assert "post" in paths["/admin/entity-verification/targets/{target_id}/recheck"]
    assert "post" in paths["/admin/entity-verification/targets/{target_id}/providers/vies/check"]


def test_entity_verification_admin_routes_contract(monkeypatch) -> None:
    fake_db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    headers = _auth_headers()
    target = _target_dto()
    summary = _summary_dto(target.id)
    check = _check_dto(target.id)

    monkeypatch.setattr(ev_router.service, "upsert_verification_target", lambda _db, payload: target)
    monkeypatch.setattr(ev_router.service, "get_target", lambda _db, target_id: target)
    monkeypatch.setattr(ev_router.service, "get_summary", lambda _db, target_id: summary)
    monkeypatch.setattr(ev_router.service, "list_checks", lambda _db, target_id, limit=100: [check])

    def _run_vies(_db, **_kwargs):
        return VerificationProviderRunDTO(
            acquired=True,
            dedup_hit=False,
            provider_called=False,
            reason="provider_result_recorded",
            applicability_status=ViesApplicabilityStatus.VIES_NOT_APPLICABLE,
            check=check,
            summary=summary,
        )

    monkeypatch.setattr(ev_router.service, "run_vies_verification_for_target", _run_vies)

    try:
        client = TestClient(app)

        upsert_resp = client.post(
            "/admin/entity-verification/targets/upsert",
            headers=headers,
            json={
                "subject_type": "PARTNER",
                "subject_id": "partner-001",
                "legal_name": "ACME",
                "country_code": "BG",
                "vat_number": "BG123456789",
            },
        )
        assert upsert_resp.status_code == 200
        assert (upsert_resp.json() or {}).get("target", {}).get("id") == target.id

        get_target_resp = client.get(f"/admin/entity-verification/targets/{target.id}", headers=headers)
        assert get_target_resp.status_code == 200
        assert (get_target_resp.json() or {}).get("target", {}).get("id") == target.id

        summary_resp = client.get(f"/admin/entity-verification/targets/{target.id}/summary", headers=headers)
        assert summary_resp.status_code == 200
        assert (summary_resp.json() or {}).get("summary", {}).get("overall_status") == "UNKNOWN"

        checks_resp = client.get(f"/admin/entity-verification/targets/{target.id}/checks", headers=headers)
        assert checks_resp.status_code == 200
        first = ((checks_resp.json() or {}).get("items") or [])[0]
        assert first.get("applicability_status") == "VIES_NOT_APPLICABLE"
        assert first.get("evidence_json") is None

        recheck_resp = client.post(
            f"/admin/entity-verification/targets/{target.id}/recheck",
            headers=headers,
            json={"provider_code": "VIES", "request_id": "req-1"},
        )
        assert recheck_resp.status_code == 200
        assert (recheck_resp.json() or {}).get("result", {}).get("acquired") is True

        provider_resp = client.post(
            f"/admin/entity-verification/targets/{target.id}/providers/vies/check",
            headers=headers,
            json={"request_id": "req-2"},
        )
        assert provider_resp.status_code == 200
        assert (provider_resp.json() or {}).get("result", {}).get("applicability_status") == "VIES_NOT_APPLICABLE"
    finally:
        app.dependency_overrides.clear()


def test_entity_verification_get_routes_do_not_trigger_provider_call(monkeypatch) -> None:
    fake_db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: fake_db
    headers = _auth_headers()
    target = _target_dto()
    summary = _summary_dto(target.id)
    check = _check_dto(target.id)

    monkeypatch.setattr(ev_router.service, "get_target", lambda _db, target_id: target)
    monkeypatch.setattr(ev_router.service, "get_summary", lambda _db, target_id: summary)
    monkeypatch.setattr(ev_router.service, "list_checks", lambda _db, target_id, limit=100: [check])

    called = SimpleNamespace(value=False)

    def _should_not_call(*_args, **_kwargs):
        called.value = True
        raise AssertionError("provider_call_must_not_happen_on_read")

    monkeypatch.setattr(ev_router.service, "run_vies_verification_for_target", _should_not_call)

    try:
        client = TestClient(app)
        assert client.get(f"/admin/entity-verification/targets/{target.id}", headers=headers).status_code == 200
        assert client.get(f"/admin/entity-verification/targets/{target.id}/summary", headers=headers).status_code == 200
        assert client.get(f"/admin/entity-verification/targets/{target.id}/checks", headers=headers).status_code == 200
        assert called.value is False
    finally:
        app.dependency_overrides.clear()

