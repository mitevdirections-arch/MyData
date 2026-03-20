from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.entity_verification.schemas import (
    PartnerVerificationRecheckResponseDTO,
    PartnerVerificationSummaryDTO,
    PartnerVerificationSummaryResponseDTO,
    ProviderStatus,
    VerificationRecheckRequestDTO,
    VerificationSummaryDTO,
    ViesApplicabilityStatus,
)
from app.modules.entity_verification.service import service as verification_service
from app.modules.partners.schemas import (
    PartnerBlacklistRequestDTO,
    PartnerDetailResponseDTO,
    PartnerGlobalSignalResponseDTO,
    PartnerRatingCreateRequestDTO,
    PartnerRatingCreateResponseDTO,
    PartnerRatingSummaryResponseDTO,
    PartnerRoleSetRequestDTO,
    PartnersListResponseDTO,
    PartnerUpdateRequestDTO,
    PartnerWatchlistRequestDTO,
    PartnerCreateRequestDTO,
)
from app.modules.partners.service import service

router = APIRouter(prefix="/partners", tags=["partners"])
admin_router = APIRouter(prefix="/admin/partners", tags=["partners"])


def _tenant_id(claims: dict[str, Any]) -> str:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    return tenant_id


def _err_status(detail: str) -> int:
    if detail in {"partner_not_found"}:
        return 404
    if detail in {"partner_code_exists"}:
        return 409
    if detail in {
        "country_code_required",
        "display_name_required",
        "partner_status_invalid",
        "partner_role_invalid",
        "payment_discipline_required_when_payment_expected",
        "payment_discipline_not_allowed_when_payment_not_expected",
        "order_id_invalid",
    }:
        return 400
    return 400


def _extract_applicability_status(evidence_json: dict[str, Any] | None) -> ViesApplicabilityStatus | None:
    raw = str((evidence_json or {}).get("applicability_status") or "").strip().upper()
    if raw in ViesApplicabilityStatus._value2member_map_:
        return ViesApplicabilityStatus(raw)
    return None


def _partner_verification_view(
    *,
    partner_id: str,
    target_id: str,
    summary: VerificationSummaryDTO,
    check: Any | None,
) -> PartnerVerificationSummaryDTO:
    provider_status = None
    applicability_status = None
    if check is not None:
        status_value = getattr(check, "status", None)
        if isinstance(status_value, ProviderStatus):
            provider_status = status_value
        else:
            provider_raw = str(status_value or "").strip().upper()
            if provider_raw.startswith("PROVIDERSTATUS."):
                provider_raw = provider_raw.split(".", 1)[1]
            if provider_raw in ProviderStatus._value2member_map_:
                provider_status = ProviderStatus(provider_raw)
        evidence_json = dict(getattr(check, "evidence_json", {}) or {})
        applicability_status = _extract_applicability_status(evidence_json)

    return PartnerVerificationSummaryDTO(
        partner_id=partner_id,
        target_id=target_id,
        overall_status=summary.overall_status,
        last_checked_at=summary.last_checked_at,
        last_verified_at=summary.last_verified_at,
        next_recommended_check_at=summary.next_recommended_check_at,
        provider_status=provider_status,
        applicability_status=applicability_status,
        provider_code="VIES",
        non_blocking=True,
    )


@router.get("", response_model=PartnersListResponseDTO)
def list_partners(
    status: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.READ")),
    db: Session = Depends(get_db_session),
) -> PartnersListResponseDTO:
    tenant_id = _tenant_id(claims)
    try:
        items = service.list_partners(db, company_id=tenant_id, status=status, include_archived=include_archived, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return PartnersListResponseDTO(ok=True, tenant_id=tenant_id, items=items)


@router.post("", response_model=PartnerDetailResponseDTO)
def create_partner(
    payload: PartnerCreateRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.WRITE")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.create_partner(db, company_id=tenant_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}",
        metadata={"partner_code": partner.partner_code, "global_company_id": partner.global_company_id},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.get("/{partner_id}", response_model=PartnerDetailResponseDTO)
def get_partner(
    partner_id: str,
    include_archived: bool = False,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.READ")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    try:
        partner = service.get_partner(db, company_id=tenant_id, partner_id=partner_id, include_archived=include_archived)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.put("/{partner_id}", response_model=PartnerDetailResponseDTO)
def update_partner(
    partner_id: str,
    payload: PartnerUpdateRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.WRITE")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.update_partner(db, company_id=tenant_id, partner_id=partner_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.updated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}",
        metadata={"partner_code": partner.partner_code},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.post("/{partner_id}/archive", response_model=PartnerDetailResponseDTO)
def archive_partner(
    partner_id: str,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.ARCHIVE")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.archive_partner(db, company_id=tenant_id, partner_id=partner_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.archived",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}",
        metadata={"partner_code": partner.partner_code},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.put("/{partner_id}/roles", response_model=PartnerDetailResponseDTO)
def set_partner_roles(
    partner_id: str,
    payload: PartnerRoleSetRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.WRITE")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.set_roles(db, company_id=tenant_id, partner_id=partner_id, roles=payload.roles)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.roles.updated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}/roles",
        metadata={"roles": [str(x) for x in partner.roles]},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.post("/{partner_id}/blacklist", response_model=PartnerDetailResponseDTO)
def set_blacklist(
    partner_id: str,
    payload: PartnerBlacklistRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.MANAGE_BLACKLIST")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.set_blacklist(
            db,
            company_id=tenant_id,
            partner_id=partner_id,
            is_blacklisted=payload.is_blacklisted,
            blacklist_reason=payload.blacklist_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.blacklist.updated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}/blacklist",
        metadata={"is_blacklisted": partner.is_blacklisted},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.post("/{partner_id}/watchlist", response_model=PartnerDetailResponseDTO)
def set_watchlist(
    partner_id: str,
    payload: PartnerWatchlistRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.MANAGE_BLACKLIST")),
    db: Session = Depends(get_db_session),
) -> PartnerDetailResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        partner = service.set_watchlist(db, company_id=tenant_id, partner_id=partner_id, is_watchlisted=payload.is_watchlisted)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.watchlist.updated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner.id}/watchlist",
        metadata={"is_watchlisted": partner.is_watchlisted},
    )
    db.commit()
    return PartnerDetailResponseDTO(ok=True, tenant_id=tenant_id, partner=partner)


@router.post("/{partner_id}/ratings", response_model=PartnerRatingCreateResponseDTO)
def create_rating(
    partner_id: str,
    payload: PartnerRatingCreateRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.RATE")),
    db: Session = Depends(get_db_session),
) -> PartnerRatingCreateResponseDTO:
    tenant_id = _tenant_id(claims)
    actor = str(claims.get("sub") or "unknown")
    try:
        rating_id, tenant_summary, global_signal = service.create_rating(
            db,
            company_id=tenant_id,
            partner_id=partner_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    write_audit(
        db,
        action="partners.rating.created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"partners/{partner_id}/ratings/{rating_id}",
        metadata={"payment_expected": payload.payment_expected},
    )
    db.commit()
    return PartnerRatingCreateResponseDTO(
        ok=True,
        tenant_id=tenant_id,
        partner_id=partner_id,
        rating_id=rating_id,
        tenant_summary=tenant_summary,
        global_signal=global_signal,
    )


@router.get("/{partner_id}/rating-summary", response_model=PartnerRatingSummaryResponseDTO)
def rating_summary(
    partner_id: str,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.READ")),
    db: Session = Depends(get_db_session),
) -> PartnerRatingSummaryResponseDTO:
    tenant_id = _tenant_id(claims)
    try:
        summary = service.get_rating_summary(db, company_id=tenant_id, partner_id=partner_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return PartnerRatingSummaryResponseDTO(ok=True, tenant_id=tenant_id, partner_id=partner_id, summary=summary)


@router.get("/{partner_id}/global-signal", response_model=PartnerGlobalSignalResponseDTO)
def global_signal(
    partner_id: str,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.VIEW_GLOBAL_SIGNAL")),
    db: Session = Depends(get_db_session),
) -> PartnerGlobalSignalResponseDTO:
    tenant_id = _tenant_id(claims)
    try:
        signal = service.get_global_signal(db, company_id=tenant_id, partner_id=partner_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return PartnerGlobalSignalResponseDTO(ok=True, tenant_id=tenant_id, partner_id=partner_id, global_signal=signal)


@admin_router.get("/{partner_id}/verification-summary", response_model=PartnerVerificationSummaryResponseDTO)
def partner_verification_summary(
    partner_id: str,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.READ")),
    db: Session = Depends(get_db_session),
) -> PartnerVerificationSummaryResponseDTO:
    tenant_id = _tenant_id(claims)
    try:
        target = service.resolve_partner_verification_target(db, company_id=tenant_id, partner_id=partner_id)
        summary = verification_service.get_summary(db, target_id=target.id)
        check = verification_service.get_latest_provider_check(db, target_id=target.id, provider_code="VIES")
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return PartnerVerificationSummaryResponseDTO(
        ok=True,
        result=_partner_verification_view(
            partner_id=partner_id,
            target_id=target.id,
            summary=summary,
            check=check,
        ),
    )


@admin_router.post("/{partner_id}/verification/recheck", response_model=PartnerVerificationRecheckResponseDTO)
def partner_verification_recheck(
    partner_id: str,
    payload: VerificationRecheckRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PARTNERS.WRITE")),
    db: Session = Depends(get_db_session),
) -> PartnerVerificationRecheckResponseDTO:
    tenant_id = _tenant_id(claims)
    provider_code = str(payload.provider_code or "VIES").strip().upper()
    if provider_code != "VIES":
        raise HTTPException(status_code=400, detail="provider_not_supported")
    actor = str(claims.get("sub") or "unknown")
    try:
        target = service.resolve_partner_verification_target(db, company_id=tenant_id, partner_id=partner_id)
        run_result = verification_service.run_vies_verification_for_target(
            db,
            target_id=target.id,
            created_by_user_id=actor,
            request_id=payload.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    summary = run_result.summary
    if summary is None:
        summary = verification_service.get_summary(db, target_id=target.id)
    return PartnerVerificationRecheckResponseDTO(
        ok=True,
        result=_partner_verification_view(
            partner_id=partner_id,
            target_id=target.id,
            summary=summary,
            check=run_result.check,
        ),
        acquired=run_result.acquired,
        dedup_hit=run_result.dedup_hit,
        provider_called=run_result.provider_called,
        reason=run_result.reason,
    )
