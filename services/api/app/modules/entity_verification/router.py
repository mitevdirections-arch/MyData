from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import enforce_permission, require_claim_permission
from app.db.session import get_db_session
from app.modules.entity_verification.schemas import (
    VerificationCheckListItemDTO,
    VerificationChecksResponseDTO,
    VerificationProviderCheckResponseDTO,
    VerificationRecheckRequestDTO,
    VerificationSummaryResponseDTO,
    VerificationTargetDetailResponseDTO,
    VerificationTargetUpsertInput,
    VerificationTargetUpsertResponseDTO,
    ViesApplicabilityStatus,
)
from app.modules.entity_verification.service import service

router = APIRouter(prefix="/admin/entity-verification", tags=["entity_verification"])


def _err_status(detail: str) -> int:
    if detail in {"target_not_found"}:
        return 404
    if detail in {"provider_not_supported"}:
        return 400
    return 400


def _to_check_item(check: Any, *, include_evidence: bool) -> VerificationCheckListItemDTO:
    evidence = dict(getattr(check, "evidence_json", {}) or {})
    applicability_raw = str(evidence.get("applicability_status") or "").strip().upper()
    applicability = None
    if applicability_raw in ViesApplicabilityStatus._value2member_map_:
        applicability = ViesApplicabilityStatus(applicability_raw)

    return VerificationCheckListItemDTO(
        id=str(check.id),
        target_id=str(check.target_id),
        provider_code=str(check.provider_code),
        check_type=str(check.check_type),
        status=check.status,
        checked_at=str(check.checked_at),
        expires_at=getattr(check, "expires_at", None),
        match_score=getattr(check, "match_score", None),
        provider_reference=getattr(check, "provider_reference", None),
        provider_message_code=getattr(check, "provider_message_code", None),
        provider_message_text=getattr(check, "provider_message_text", None),
        applicability_status=applicability,
        evidence_json=(evidence if include_evidence else None),
    )


@router.post("/targets/upsert", response_model=VerificationTargetUpsertResponseDTO)
def upsert_target(
    payload: VerificationTargetUpsertInput,
    _claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.admin")),
    db: Session = Depends(get_db_session),
) -> VerificationTargetUpsertResponseDTO:
    try:
        target = service.upsert_verification_target(db, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return VerificationTargetUpsertResponseDTO(ok=True, target=target)


@router.get("/targets/{target_id}", response_model=VerificationTargetDetailResponseDTO)
def get_target(
    target_id: str,
    _claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.read")),
    db: Session = Depends(get_db_session),
) -> VerificationTargetDetailResponseDTO:
    try:
        target = service.get_target(db, target_id=target_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return VerificationTargetDetailResponseDTO(ok=True, target=target)


@router.get("/targets/{target_id}/summary", response_model=VerificationSummaryResponseDTO)
def get_summary(
    target_id: str,
    _claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.read")),
    db: Session = Depends(get_db_session),
) -> VerificationSummaryResponseDTO:
    try:
        summary = service.get_summary(db, target_id=target_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return VerificationSummaryResponseDTO(ok=True, target_id=target_id, summary=summary)


@router.get("/targets/{target_id}/checks", response_model=VerificationChecksResponseDTO)
def list_checks(
    target_id: str,
    include_evidence: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.read")),
    db: Session = Depends(get_db_session),
) -> VerificationChecksResponseDTO:
    if include_evidence:
        enforce_permission(claims, "entity_verification.read_evidence")
    try:
        checks = service.list_checks(db, target_id=target_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    items = [_to_check_item(x, include_evidence=include_evidence) for x in checks]
    return VerificationChecksResponseDTO(ok=True, target_id=target_id, items=items)


@router.post("/targets/{target_id}/recheck", response_model=VerificationProviderCheckResponseDTO)
def recheck_target(
    target_id: str,
    payload: VerificationRecheckRequestDTO = Body(default_factory=VerificationRecheckRequestDTO),
    claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.recheck")),
    db: Session = Depends(get_db_session),
) -> VerificationProviderCheckResponseDTO:
    provider_code = str(payload.provider_code or "VIES").strip().upper()
    if provider_code != "VIES":
        raise HTTPException(status_code=400, detail="provider_not_supported")
    actor = str(claims.get("sub") or "unknown")
    try:
        result = service.run_vies_verification_for_target(
            db,
            target_id=target_id,
            created_by_user_id=actor,
            request_id=payload.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return VerificationProviderCheckResponseDTO(ok=True, result=result)


@router.post("/targets/{target_id}/providers/vies/check", response_model=VerificationProviderCheckResponseDTO)
def check_vies_for_target(
    target_id: str,
    payload: VerificationRecheckRequestDTO = Body(default_factory=VerificationRecheckRequestDTO),
    claims: dict[str, Any] = Depends(require_claim_permission("entity_verification.check")),
    db: Session = Depends(get_db_session),
) -> VerificationProviderCheckResponseDTO:
    actor = str(claims.get("sub") or "unknown")
    try:
        result = service.run_vies_verification_for_target(
            db,
            target_id=target_id,
            created_by_user_id=actor,
            request_id=payload.request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return VerificationProviderCheckResponseDTO(ok=True, result=result)

