from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claims, require_superadmin, require_tenant_admin
from app.db.session import get_db_session
from app.modules.licensing.core_catalog import DEFAULT_CORE_PLAN_CODE
from app.modules.licensing.service import service

router = APIRouter(prefix="/licenses", tags=["licensing"])


@router.get("/active")
def list_active(claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    items = service.list_active(db=db, tenant_id=tenant_id)
    return {"ok": True, "items": items}


@router.get("/core-entitlement")
def core_entitlement(claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    out = service.resolve_core_entitlement(db=db, tenant_id=tenant_id)
    out["active_leased_users"] = service.count_active_leased_users(db=db, tenant_id=tenant_id)
    out["available_seats"] = None if out.get("seat_limit") is None else max(0, int(out["seat_limit"]) - int(out["active_leased_users"]))
    return {"ok": True, "tenant_id": tenant_id, **out}




@router.get("/entitlement-v2")
def entitlement_v2(claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    out = service.entitlement_snapshot_v2(db=db, tenant_id=tenant_id)
    return {"ok": True, **out}
@router.get("/module-entitlement/{module_code}")
def module_entitlement(module_code: str, claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    code = str(module_code or "").strip().upper()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    if not code:
        raise HTTPException(status_code=400, detail="module_code_required")

    out = service.resolve_module_entitlement(db=db, tenant_id=tenant_id, module_code=code)
    return {"ok": True, "tenant_id": tenant_id, **out}


@router.post("/admin/visual-code-preview")
def visual_code_preview(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    license_type = str(payload.get("license_type") or "MODULE_TRIAL").strip().upper()
    module_code = str(payload.get("module_code") or "").strip().upper() or None
    vat_number = payload.get("vat_number")
    internal_mark = payload.get("internal_mark")

    issued_at: datetime | None = None
    raw_ts = payload.get("issued_at")
    if raw_ts:
        try:
            issued_at = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if issued_at.tzinfo is None:
                issued_at = issued_at.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="issued_at_invalid_iso") from exc

    preview = service.preview_visual_code(
        db,
        tenant_id=tenant_id,
        license_type=license_type,
        module_code=module_code,
        vat_number=(str(vat_number).strip() if vat_number is not None else None),
        issued_at=issued_at,
        internal_mark=(str(internal_mark).strip() if internal_mark is not None else None),
    )
    return {"ok": True, "tenant_id": tenant_id, "preview": preview}


@router.get("/admin/issuance-policy")
def get_issuance_policy(tenant_id: str, claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id_required")
    out = service.get_issuance_policy(db, tenant_id=tid)
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), **out}


@router.put("/admin/issuance-policy")
def set_issuance_policy(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tid = str(payload.get("tenant_id") or "").strip()
    mode = str(payload.get("mode") or "").strip().upper()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id_required")
    if not mode:
        raise HTTPException(status_code=400, detail="mode_required")

    out = service.set_issuance_policy(db, tenant_id=tid, mode=mode, actor=str(claims.get("sub") or "unknown"))
    write_audit(
        db,
        action="licensing.issuance_policy_set",
        actor=claims.get("sub", "unknown"),
        tenant_id=tid,
        target="license/issuance-policy",
        metadata={"mode": out.get("mode")},
    )
    db.commit()
    return {"ok": True, **out}


@router.get("/admin/issue-requests")
def list_issue_requests(
    tenant_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    out = service.list_issue_requests(
        db,
        tenant_id=(str(tenant_id).strip() if tenant_id else None),
        status=(str(status).strip().upper() if status else None),
        limit=limit,
    )
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": out}


@router.post("/admin/issue-startup")
def issue_startup(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    admin_confirmed = bool(payload.get("admin_confirmed", False))
    note = str(payload.get("note") or "").strip() or None
    core_plan_code = str(payload.get("core_plan_code") or "").strip() or None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    try:
        out = service.request_startup_with_policy(
            db,
            tenant_id=tenant_id,
            requested_by=str(claims.get("sub") or "unknown"),
            admin_confirmed=admin_confirmed,
            note=note,
            core_plan_code=core_plan_code,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 409 if detail == "startup_non_renewable" else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    action = "licensing.issue_startup_issued" if out.get("flow") == "ISSUED" else "licensing.issue_startup_requested"
    write_audit(
        db,
        action=action,
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target="license/startup",
        metadata={
            "mode": out.get("mode"),
            "flow": out.get("flow"),
            "admin_confirmed": admin_confirmed,
            "request_id": (out.get("request") or {}).get("id"),
            "issued": out.get("issued"),
            "license_visual_codes": out.get("license_visual_codes"),
        },
    )
    db.commit()
    return out


@router.post("/admin/issue-requests/{request_id}/approve")
def approve_issue_request(request_id: str, payload: dict[str, Any] | None = None, claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    body = payload or {}
    note = str(body.get("note") or "").strip() or None
    try:
        out = service.approve_issue_request(
            db,
            request_id=request_id,
            approved_by=str(claims.get("sub") or "unknown"),
            note=note,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "request_not_found" else 409 if detail in {"startup_non_renewable", "request_not_pending"} else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    req = out.get("request") or {}
    write_audit(
        db,
        action="licensing.issue_request_approved",
        actor=claims.get("sub", "unknown"),
        tenant_id=req.get("tenant_id"),
        target=f"license/request/{request_id}",
        metadata={"request_type": req.get("request_type"), "status": req.get("status")},
    )
    db.commit()
    return out


@router.post("/admin/issue-requests/{request_id}/reject")
def reject_issue_request(request_id: str, payload: dict[str, Any] | None = None, claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    body = payload or {}
    note = str(body.get("note") or "").strip() or None
    try:
        out = service.reject_issue_request(
            db,
            request_id=request_id,
            approved_by=str(claims.get("sub") or "unknown"),
            note=note,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "request_not_found" else 409 if detail == "request_not_pending" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    req = out.get("request") or {}
    write_audit(
        db,
        action="licensing.issue_request_rejected",
        actor=claims.get("sub", "unknown"),
        tenant_id=req.get("tenant_id"),
        target=f"license/request/{request_id}",
        metadata={"request_type": req.get("request_type"), "status": req.get("status")},
    )
    db.commit()
    return out



@router.post("/admin/issue-core")
def issue_core(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    plan_code = str(payload.get("plan_code") or DEFAULT_CORE_PLAN_CODE).strip().upper()
    valid_days_raw = payload.get("valid_days")

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    try:
        valid_days = int(valid_days_raw) if valid_days_raw is not None else 30
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="valid_days_invalid") from exc

    try:
        out = service.issue_core_only(db=db, tenant_id=tenant_id, plan_code=plan_code, days=valid_days)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "tenant_not_found" else 409 if detail == "core_already_active" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="licensing.issue_core",
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target="license/core",
        metadata={
            "plan_code": plan_code,
            "valid_days": valid_days,
            "license_visual_code": ((out.get("license") or {}).get("license_visual_code")),
        },
    )
    db.commit()
    return out


@router.post("/admin/issue-module-trial")
def issue_module_trial(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    module_code = str(payload.get("module_code") or "").strip().upper()
    if not tenant_id or not module_code:
        raise HTTPException(status_code=400, detail="tenant_id_and_module_code_required")

    try:
        out = service.issue_module_trial(db=db, tenant_id=tenant_id, module_code=module_code)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    write_audit(
        db,
        action="licensing.issue_module_trial",
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target=f"license/module/{module_code}",
        metadata={"license_visual_code": out.get("license_visual_code")},
    )
    db.commit()
    return out
