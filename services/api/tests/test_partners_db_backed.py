from __future__ import annotations

import os
import time
import uuid

import pytest

from app.db.models import GlobalCompany, GlobalCompanyReputation, Tenant, TenantPartnerRatingSummary
from app.db.session import get_engine, get_session_factory
from app.modules.partners.schemas import PartnerCreateRequestDTO, PartnerRatingCreateRequestDTO
from app.modules.partners.service import PartnersService


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_db_backed_mode() -> None:
    if not _truthy(os.getenv("PARTNERS_DB_BACKED_ENABLED")):
        pytest.skip("PARTNERS_DB_BACKED_ENABLED is not true")
    if not str(os.getenv("DATABASE_URL") or "").strip():
        pytest.fail("DATABASE_URL is required for partners db-backed tests")


def _seed_tenant(db) -> str:
    tenant_id = f"tenant-partners-{uuid.uuid4().hex[:10]}"
    db.add(Tenant(id=tenant_id, name=f"Partners DB {tenant_id}", is_active=True))
    db.flush()
    return tenant_id


@pytest.mark.integration
def test_partners_dedupe_contract_db_backed() -> None:
    _require_db_backed_mode()
    get_engine.cache_clear()
    db = get_session_factory()()
    service = PartnersService()
    try:
        tenant_id = _seed_tenant(db)
        u = uuid.uuid4().hex[:8].upper()

        first = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"ACME {u}",
                country_code="BG",
                vat_number=f"BGVAT-{u}",
                registration_number=f"REG-{u}-A",
            ),
        )
        second = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"ACME SAME VAT {u}",
                country_code="BG",
                vat_number=f"BGVAT-{u}",
                registration_number=f"REG-{u}-B",
            ),
        )
        assert first.global_company_id is not None
        assert second.global_company_id == first.global_company_id

        reg1 = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"REG PARTNER {u}",
                country_code="BG",
                registration_number=f"REG-ONLY-{u}",
            ),
        )
        reg2 = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"REG PARTNER ALT {u}",
                country_code="BG",
                registration_number=f"REG-ONLY-{u}",
            ),
        )
        assert reg1.global_company_id is not None
        assert reg2.global_company_id == reg1.global_company_id

        name1 = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"Nova Cargo {u}",
                country_code="BG",
            ),
        )
        name2 = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"NOVA-CARGO {u}",
                country_code="BG",
            ),
        )
        assert name1.global_company_id is not None
        assert name2.global_company_id == name1.global_company_id

        ambiguous_vat = f"BG-AMB-{u}"
        gc1 = GlobalCompany(
            canonical_name=f"AMB-1 {u}",
            legal_name=f"AMB-1 {u}",
            country_code="BG",
            vat_number=ambiguous_vat,
            registration_number=None,
            website_url=None,
            main_email=None,
            main_phone=None,
            normalized_name=f"AMB1{u}",
            status="ACTIVE",
        )
        gc2 = GlobalCompany(
            canonical_name=f"AMB-2 {u}",
            legal_name=f"AMB-2 {u}",
            country_code="BG",
            vat_number=ambiguous_vat,
            registration_number=None,
            website_url=None,
            main_email=None,
            main_phone=None,
            normalized_name=f"AMB2{u}",
            status="ACTIVE",
        )
        db.add(gc1)
        db.add(gc2)
        db.flush()

        ambiguous_partner = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"AMB TARGET {u}",
                country_code="BG",
                vat_number=ambiguous_vat,
            ),
        )
        assert ambiguous_partner.global_company_id is not None
        assert ambiguous_partner.global_company_id not in {str(gc1.id), str(gc2.id)}
    finally:
        db.rollback()
        db.close()
        get_engine.cache_clear()


@pytest.mark.integration
def test_partners_scoped_summary_recompute_db_backed() -> None:
    _require_db_backed_mode()
    get_engine.cache_clear()
    db = get_session_factory()()
    service = PartnersService()
    try:
        tenant_id = _seed_tenant(db)
        u = uuid.uuid4().hex[:8].upper()

        a = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"Scoped A {u}",
                country_code="BG",
                vat_number=f"BG-A-{u}",
            ),
        )
        b = service.create_partner(
            db,
            company_id=tenant_id,
            payload=PartnerCreateRequestDTO(
                display_name=f"Scoped B {u}",
                country_code="BG",
                vat_number=f"BG-B-{u}",
            ),
        )
        assert a.global_company_id is not None
        assert b.global_company_id is not None

        service.create_rating(
            db,
            company_id=tenant_id,
            partner_id=b.id,
            actor="owner@tenant.local",
            payload=PartnerRatingCreateRequestDTO(
                execution_quality_stars=6,
                communication_docs_stars=4,
                payment_expected=False,
                short_comment="tenant-local b",
            ),
        )

        b_pid = uuid.UUID(b.id)
        b_gid = uuid.UUID(b.global_company_id)
        b_summary = db.query(TenantPartnerRatingSummary).filter(TenantPartnerRatingSummary.partner_id == b_pid).first()
        b_rep = db.query(GlobalCompanyReputation).filter(GlobalCompanyReputation.global_company_id == b_gid).first()
        assert b_summary is not None
        assert b_rep is not None
        assert int(b_summary.rating_count) == 1
        assert int(b_rep.total_completed_orders_rated) == 1
        b_summary_updated_before = b_summary.updated_at
        b_rep_updated_before = b_rep.updated_at

        time.sleep(0.02)
        service.create_rating(
            db,
            company_id=tenant_id,
            partner_id=a.id,
            actor="owner@tenant.local",
            payload=PartnerRatingCreateRequestDTO(
                execution_quality_stars=5,
                communication_docs_stars=5,
                payment_expected=False,
                short_comment="tenant-local a",
            ),
        )

        b_summary_after = db.query(TenantPartnerRatingSummary).filter(TenantPartnerRatingSummary.partner_id == b_pid).first()
        b_rep_after = db.query(GlobalCompanyReputation).filter(GlobalCompanyReputation.global_company_id == b_gid).first()
        assert b_summary_after is not None
        assert b_rep_after is not None
        assert int(b_summary_after.rating_count) == 1
        assert int(b_rep_after.total_completed_orders_rated) == 1
        assert b_summary_after.updated_at == b_summary_updated_before
        assert b_rep_after.updated_at == b_rep_updated_before
    finally:
        db.rollback()
        db.close()
        get_engine.cache_clear()
