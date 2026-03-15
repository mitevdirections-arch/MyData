from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.audit import write_audit
from app.core.auth import require_superadmin_permission, require_tenant_admin_permission
from app.db.session import get_db_session
from app.modules.marketplace.service import service
router = APIRouter(prefix="/marketplace", tags=["marketplace"])
def _err_status(detail: str) -> int:
    if detail in {"tenant_not_found", "module_not_found", "offer_not_found", "marketplace_request_not_found"}:
        return 404
    if detail in {"core_required", "core_license_required", "deferred_credit_limit_exceeded", "deferred_account_on_hold", "deferred_account_not_active", "deferred_account_required", "deferred_mode_not_enabled", "deferred_currency_mismatch"}:
        return 402
    if detail in {"module_already_licensed", "marketplace_request_not_pending", "offer_code_exists", "invoice_compliance_missing_fields"}:
        return 409
    if detail == "missing_tenant_context":
        return 403
    return 400
@router.get("/catalog")
def tenant_catalog(
    module_class: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        items = service.list_catalog(db, tenant_id=tenant_id, module_class=module_class, include_inactive=False, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    db.commit()
    return {"ok": True, "tenant_id": tenant_id, "items": items}
@router.get("/offers/active")
def tenant_active_offers(
    module_code: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        items = service.list_active_offers(db, module_code=module_code, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "tenant_id": tenant_id, "items": items}
@router.post("/purchase-requests")
def tenant_request_purchase(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        out = service.request_purchase(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    write_audit(
        db,
        action=("marketplace.purchase.issued_auto" if out.get("flow") == "ISSUED" else "marketplace.purchase.requested"),
        actor=actor,
        tenant_id=tenant_id,
        target=f"marketplace/module/{out.get('module_code')}",
        metadata={
            "flow": out.get("flow"),
            "mode": out.get("mode"),
            "request_id": (out.get("request") or {}).get("id"),
            "offer_code": (out.get("offer") or {}).get("code"),
            "issued_license_id": (out.get("issued") or {}).get("license_id"),
            "payment_flow": (out.get("payment") or {}).get("flow"),
            "invoice_id": (((out.get("payment") or {}).get("invoice") or {}).get("id")),
        },
    )
    db.commit()
    return out
@router.get("/purchase-requests")
def tenant_list_purchase_requests(
    status: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    items = service.list_tenant_requests(db, tenant_id=tenant_id, status=status, limit=limit)
    return {"ok": True, "tenant_id": tenant_id, "items": items}
@router.get("/admin/catalog")
def super_catalog(
    module_class: str | None = None,
    include_inactive: bool = True,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_catalog(db, tenant_id=None, module_class=module_class, include_inactive=include_inactive, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    db.commit()
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}
@router.put("/admin/catalog/{module_code}")
def super_upsert_module(
    module_code: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_module(db, actor=actor, payload=payload, module_code=module_code)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    write_audit(
        db,
        action="marketplace.catalog.upsert",
        actor=actor,
        tenant_id="superadmin",
        target=f"marketplace/catalog/{out.get('module_code')}",
        metadata={"is_active": out.get("is_active"), "price_minor": out.get("base_price_minor")},
    )
    db.commit()
    return {"ok": True, "item": out}
@router.get("/admin/offers")
def super_list_offers(
    status: str | None = None,
    module_code: str | None = None,
    include_expired: bool = True,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_offers(db, status=status, module_code=module_code, include_expired=include_expired, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}
@router.post("/admin/offers")
def super_create_offer(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_offer(db, actor=actor, payload=payload, offer_id=None)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    write_audit(
        db,
        action="marketplace.offer.created",
        actor=actor,
        tenant_id="superadmin",
        target=f"marketplace/offer/{out.get('id')}",
        metadata={"code": out.get("code"), "status": out.get("status"), "module_code": out.get("module_code")},
    )
    db.commit()
    return {"ok": True, "item": out}
@router.put("/admin/offers/{offer_id}")
def super_update_offer(
    offer_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_offer(db, actor=actor, payload=payload, offer_id=offer_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    write_audit(
        db,
        action="marketplace.offer.updated",
        actor=actor,
        tenant_id="superadmin",
        target=f"marketplace/offer/{offer_id}",
        metadata={"code": out.get("code"), "status": out.get("status"), "module_code": out.get("module_code")},
    )
    db.commit()
    return {"ok": True, "item": out}
@router.get("/admin/purchase-requests")
def super_list_purchase_requests(
    tenant_id: str | None = None,
    status: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    items = service.list_super_requests(db, tenant_id=tenant_id, status=status, limit=limit)
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}
@router.post("/admin/purchase-requests/{request_id}/approve")
def super_approve_request(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    try:
        out = service.approve_request(
            db,
            request_id=request_id,
            actor=actor,
            note=(str(body.get("note") or "").strip() or None),
            valid_days=(int(body.get("valid_days")) if "valid_days" in body and body.get("valid_days") is not None else None),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    req = out.get("request") or {}
    issued = out.get("issued") or {}
    write_audit(
        db,
        action="marketplace.purchase.approved",
        actor=actor,
        tenant_id=req.get("tenant_id"),
        target=f"marketplace/request/{request_id}",
        metadata={"module_code": (req.get("payload") or {}).get("module_code"), "license_id": issued.get("license_id"), "invoice_id": ((((out.get("payment") or {}).get("invoice") or {}).get("id")))},
    )
    db.commit()
    return out
@router.post("/admin/purchase-requests/{request_id}/reject")
def super_reject_request(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("MARKETPLACE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    try:
        out = service.reject_request(
            db,
            request_id=request_id,
            actor=actor,
            note=(str(body.get("note") or "").strip() or None),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc
    req = out.get("request") or {}
    write_audit(
        db,
        action="marketplace.purchase.rejected",
        actor=actor,
        tenant_id=req.get("tenant_id"),
        target=f"marketplace/request/{request_id}",
        metadata={"module_code": (req.get("payload") or {}).get("module_code")},
    )
    db.commit()
    return out
