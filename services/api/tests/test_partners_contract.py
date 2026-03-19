from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
import app.modules.partners.router as partners_router
from app.modules.partners.schemas import (
    GlobalCompanySignalDTO,
    PartnerAddressDTO,
    PartnerBankAccountDTO,
    PartnerContactDTO,
    PartnerCreateRequestDTO,
    PartnerDetailDTO,
    PartnerDocumentDTO,
    PartnerRoleCode,
    PartnerSummaryDTO,
    TenantPartnerRatingSummaryDTO,
)


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _token() -> str:
    return create_access_token({"sub": "owner@tenant.local", "roles": ["TENANT_ADMIN"], "tenant_id": "tenant-001"})


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _summary() -> PartnerSummaryDTO:
    return PartnerSummaryDTO(
        id="5f863653-5f56-4978-a0eb-c87cf348cc5e",
        company_id="tenant-001",
        global_company_id="aa3d1208-bc72-4ba8-a4be-f2cf405b83ea",
        partner_code="PARTNER-ACME",
        display_name="ACME",
        legal_name="ACME LTD",
        country_code="BG",
        vat_number="BG123",
        registration_number="REG123",
        website_url="https://acme.example",
        main_email="ops@acme.example",
        main_phone="+35910000000",
        status="ACTIVE",
        is_blacklisted=False,
        is_watchlisted=False,
        blacklist_reason=None,
        created_at="2026-03-19T10:00:00+00:00",
        updated_at="2026-03-19T10:00:00+00:00",
        archived_at=None,
    )


def _detail() -> PartnerDetailDTO:
    return PartnerDetailDTO(
        **_summary().model_dump(),
        internal_note="tenant-private-note",
        roles=[PartnerRoleCode.CARRIER],
        addresses=[PartnerAddressDTO(address_type="HQ", city="Sofia", country_code="BG")],
        bank_accounts=[PartnerBankAccountDTO(account_holder="ACME LTD", iban="BG00TEST")],
        contacts=[PartnerContactDTO(contact_name="Ops", email="ops@acme.example")],
        documents=[PartnerDocumentDTO(doc_type="CONTRACT", file_name="contract.pdf", storage_key="partners/acme/contract.pdf")],
        rating_summary=TenantPartnerRatingSummaryDTO(
            partner_id=_summary().id,
            rating_count=1,
            avg_execution_quality=5.0,
            avg_communication_docs=4.0,
            avg_payment_discipline=3.0,
            avg_overall_score=4.0,
            last_rating_at="2026-03-19T10:00:00+00:00",
            payment_issue_count=0,
            updated_at="2026-03-19T10:00:00+00:00",
        ),
    )


def _signal() -> GlobalCompanySignalDTO:
    return GlobalCompanySignalDTO(
        global_company_id=_summary().global_company_id or "",
        canonical_name="ACME",
        legal_name="ACME LTD",
        country_code="BG",
        vat_number="BG123",
        registration_number="REG123",
        status="ACTIVE",
        total_tenants=1,
        total_completed_orders_rated=1,
        avg_execution_quality=5.0,
        avg_communication_docs=4.0,
        avg_payment_discipline=3.0,
        global_overall_score=4.0,
        risk_payment_count=0,
        risk_quality_count=0,
        blacklist_signal_count=0,
        updated_at="2026-03-19T10:00:00+00:00",
    )


def test_partners_contract_endpoints_smoke(monkeypatch) -> None:
    db = _FakeDB()
    app.dependency_overrides[get_db_session] = lambda: db

    monkeypatch.setattr(partners_router, "write_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(partners_router.service, "list_partners", lambda *_args, **_kwargs: [_summary()])
    monkeypatch.setattr(partners_router.service, "create_partner", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "get_partner", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "update_partner", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "archive_partner", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "set_roles", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "set_blacklist", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(partners_router.service, "set_watchlist", lambda *_args, **_kwargs: _detail())
    monkeypatch.setattr(
        partners_router.service,
        "create_rating",
        lambda *_args, **_kwargs: (
            "cf646ad3-2d5a-49c7-9f31-952d04c46ebb",
            _detail().rating_summary,
            _signal(),
        ),
    )
    monkeypatch.setattr(partners_router.service, "get_rating_summary", lambda *_args, **_kwargs: _detail().rating_summary)
    monkeypatch.setattr(partners_router.service, "get_global_signal", lambda *_args, **_kwargs: _signal())

    try:
        client = TestClient(app)
        assert client.get("/partners", headers=_headers()).status_code == 200
        assert client.post("/partners", headers=_headers(), json=PartnerCreateRequestDTO(display_name="ACME", country_code="BG").model_dump()).status_code == 200
        assert client.get(f"/partners/{_summary().id}", headers=_headers()).status_code == 200
        assert client.put(f"/partners/{_summary().id}", headers=_headers(), json={"display_name": "ACME 2"}).status_code == 200
        assert client.post(f"/partners/{_summary().id}/archive", headers=_headers()).status_code == 200
        assert client.put(f"/partners/{_summary().id}/roles", headers=_headers(), json={"roles": ["CARRIER", "SUPPLIER"]}).status_code == 200
        assert client.post(f"/partners/{_summary().id}/blacklist", headers=_headers(), json={"is_blacklisted": True, "blacklist_reason": "test"}).status_code == 200
        assert client.post(f"/partners/{_summary().id}/watchlist", headers=_headers(), json={"is_watchlisted": True}).status_code == 200

        rating_resp = client.post(
            f"/partners/{_summary().id}/ratings",
            headers=_headers(),
            json={
                "execution_quality_stars": 5,
                "communication_docs_stars": 4,
                "payment_expected": True,
                "payment_discipline_stars": 3,
                "short_comment": "tenant-private-only",
            },
        )
        assert rating_resp.status_code == 200

        summary_resp = client.get(f"/partners/{_summary().id}/rating-summary", headers=_headers())
        assert summary_resp.status_code == 200
        global_resp = client.get(f"/partners/{_summary().id}/global-signal", headers=_headers())
        assert global_resp.status_code == 200

        global_json = global_resp.json() or {}
        signal_obj = global_json.get("global_signal") or {}
        assert "short_comment" not in signal_obj
        assert "internal_note" not in signal_obj
    finally:
        app.dependency_overrides.pop(get_db_session, None)
