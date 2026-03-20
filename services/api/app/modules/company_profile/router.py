from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.company_profile.service import service
from app.modules.entity_verification.schemas import (
    CompanyVerificationRecheckResponseDTO,
    CompanyVerificationSummaryDTO,
    CompanyVerificationSummaryResponseDTO,
    ProviderStatus,
    VerificationRecheckRequestDTO,
    VerificationSummaryDTO,
    ViesApplicabilityStatus,
)
from app.modules.entity_verification.service import service as verification_service
from app.modules.profile.router_parts.common import _ensure_workspace_admin_or_403, _resolve_scope_or_400

router = APIRouter(prefix="/admin/company", tags=["company_profile"])


def _err_status(detail: str) -> int:
    if detail in {"tenant_not_found"}:
        return 404
    if detail in {"provider_not_supported"}:
        return 400
    return 400


def _extract_applicability_status(evidence_json: dict[str, Any] | None) -> ViesApplicabilityStatus | None:
    raw = str((evidence_json or {}).get("applicability_status") or "").strip().upper()
    if raw in ViesApplicabilityStatus._value2member_map_:
        return ViesApplicabilityStatus(raw)
    return None


def _company_verification_view(
    *,
    target_id: str,
    summary: VerificationSummaryDTO,
    check: Any | None,
) -> CompanyVerificationSummaryDTO:
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

    return CompanyVerificationSummaryDTO(
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


@router.get("/verification-summary", response_model=CompanyVerificationSummaryResponseDTO)
def company_verification_summary(
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> CompanyVerificationSummaryResponseDTO:
    _ensure_workspace_admin_or_403(claims)
    workspace_type, workspace_id = _resolve_scope_or_400(claims, "TENANT", db)
    actor = str(claims.get("sub") or "unknown")
    try:
        target = service.resolve_tenant_company_verification_target(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            actor=actor,
        )
        summary = verification_service.get_summary(db, target_id=target.id)
        check = verification_service.get_latest_provider_check(db, target_id=target.id, provider_code="VIES")
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return CompanyVerificationSummaryResponseDTO(
        ok=True,
        result=_company_verification_view(target_id=target.id, summary=summary, check=check),
    )


@router.post("/verification/recheck", response_model=CompanyVerificationRecheckResponseDTO)
def company_verification_recheck(
    payload: VerificationRecheckRequestDTO,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> CompanyVerificationRecheckResponseDTO:
    _ensure_workspace_admin_or_403(claims)
    workspace_type, workspace_id = _resolve_scope_or_400(claims, "TENANT", db)
    provider_code = str(payload.provider_code or "VIES").strip().upper()
    if provider_code != "VIES":
        raise HTTPException(status_code=400, detail="provider_not_supported")
    actor = str(claims.get("sub") or "unknown")
    try:
        target = service.resolve_tenant_company_verification_target(
            db,
            workspace_type=workspace_type,
            workspace_id=workspace_id,
            actor=actor,
        )
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
    return CompanyVerificationRecheckResponseDTO(
        ok=True,
        result=_company_verification_view(target_id=target.id, summary=summary, check=run_result.check),
        acquired=run_result.acquired,
        dedup_hit=run_result.dedup_hit,
        provider_called=run_result.provider_called,
        reason=run_result.reason,
    )

