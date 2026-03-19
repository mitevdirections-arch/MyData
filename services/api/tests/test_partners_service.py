from __future__ import annotations

from types import SimpleNamespace
import uuid

from app.modules.partners.schemas import GlobalCompanySignalDTO, PartnerRatingCreateRequestDTO, TenantPartnerRatingSummaryDTO
from app.modules.partners.service import PartnersService


class _FakeDB:
    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", uuid.uuid4())

    def flush(self) -> None:
        return None


def test_partners_rating_formula_v1() -> None:
    service = PartnersService()

    without_payment = SimpleNamespace(
        payment_expected=False,
        execution_quality_stars=6,
        communication_docs_stars=4,
        payment_discipline_stars=None,
    )
    with_payment = SimpleNamespace(
        payment_expected=True,
        execution_quality_stars=6,
        communication_docs_stars=4,
        payment_discipline_stars=2,
    )

    assert service._overall_score(without_payment) == 5.0
    assert service._overall_score(with_payment) == 4.0


def test_create_rating_triggers_scoped_summary_recompute(monkeypatch) -> None:
    service = PartnersService()
    db = _FakeDB()

    partner_id = uuid.uuid4()
    global_company_id = uuid.uuid4()
    calls: dict[str, int] = {"tenant": 0, "global": 0}

    monkeypatch.setattr(
        service,
        "_partner_row",
        lambda _db, *, company_id, partner_id, include_archived=False: SimpleNamespace(
            id=uuid.UUID(partner_id),
            company_id=company_id,
            global_company_id=global_company_id,
            archived_at=None,
        ),
    )
    monkeypatch.setattr(
        service,
        "_recompute_tenant_summary",
        lambda _db, *, company_id, partner_id: calls.__setitem__("tenant", calls["tenant"] + 1)
        or SimpleNamespace(
            partner_id=partner_id,
            rating_count=1,
            avg_execution_quality=5.0,
            avg_communication_docs=4.0,
            avg_payment_discipline=3.0,
            avg_overall_score=4.0,
            last_rating_at=None,
            payment_issue_count=0,
            updated_at=None,
        ),
    )
    monkeypatch.setattr(
        service,
        "_recompute_global_summary",
        lambda _db, *, global_company_id=None: calls.__setitem__("global", calls["global"] + 1),
    )
    monkeypatch.setattr(
        service,
        "_global_signal",
        lambda _db, *, global_company_id=None: GlobalCompanySignalDTO(
            global_company_id=str(global_company_id),
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
            updated_at=None,
        ),
    )

    payload = PartnerRatingCreateRequestDTO(
        payment_expected=True,
        execution_quality_stars=5,
        communication_docs_stars=4,
        payment_discipline_stars=3,
        short_comment="tenant-local comment",
    )
    rating_id, tenant_summary, global_signal = service.create_rating(
        db,
        company_id="tenant-001",
        partner_id=str(partner_id),
        actor="owner@tenant.local",
        payload=payload,
    )

    assert str(rating_id).strip() != ""
    assert isinstance(tenant_summary, TenantPartnerRatingSummaryDTO)
    assert global_signal is not None
    assert calls["tenant"] == 1
    assert calls["global"] == 1
