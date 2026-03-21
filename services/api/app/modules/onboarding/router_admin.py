from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin
from app.db.session import get_db_session
from app.modules.onboarding.service import service

router = APIRouter(prefix="/admin/onboarding", tags=["admin.onboarding"])


@router.get("/applications")
def list_applications(
    limit: int = 50,
    offset: int = 0,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    out = service.list_applications(db=db, limit=limit, offset=offset)
    out["requested_by"] = claims.get("sub", "unknown")
    return out


@router.post("/applications/{application_id}/approve")
def approve_application(
    application_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.approve_application_and_provision(
            db=db,
            application_id=application_id,
            actor=actor,
            payload=dict(payload or {}),
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "application_not_found" else 409 if detail in {"application_already_approved", "application_approval_in_progress"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    app_item = out.get("application") or {}
    provisioning_summary = ((out.get("provisioning") or {}).get("summary") or {})
    provisioned_tenant_id = provisioning_summary.get("tenant_id")
    write_audit(
        db,
        action="onboarding.application.approved",
        actor=actor,
        tenant_id=provisioned_tenant_id,
        target=f"onboarding/application/{application_id}",
        metadata={
            "application_id": app_item.get("id"),
            "status": app_item.get("status"),
            "core_plan_code": app_item.get("core_plan_code"),
            "provisioning_tenant_id": provisioned_tenant_id,
        },
    )
    db.commit()
    return out
