from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin_permission, require_tenant_admin_permission
from app.db.session import get_db_session
from app.modules.payments.service import service

admin_router = APIRouter(prefix="/admin/payments", tags=["admin.payments"])
super_router = APIRouter(prefix="/superadmin/payments", tags=["superadmin.payments"])


def _err_status(detail: str) -> int:
    if detail in {"tenant_not_found", "invoice_not_found"}:
        return 404
    if detail in {
        "deferred_credit_limit_exceeded",
        "deferred_account_on_hold",
        "deferred_account_not_active",
        "deferred_account_required",
        "deferred_mode_not_enabled",
    }:
        return 402
    if detail in {"invoice_not_payable", "partial_payment_not_supported", "invoice_compliance_missing_fields"}:
        return 409
    return 400


@admin_router.get("/credit-account")
def tenant_credit_account(
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    out = service.resolve_tenant_payment_profile(db, tenant_id=tenant_id)
    return {"ok": True, "tenant_id": tenant_id, "account": out}


@admin_router.get("/invoices")
def tenant_invoices(
    status: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        items = service.list_invoices(db, tenant_id=tenant_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return {"ok": True, "tenant_id": tenant_id, "items": items}


@admin_router.get("/invoice-template")
def tenant_invoice_template_policy(
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    out = service.get_invoice_template_policy(db, tenant_id=tenant_id)
    return {"ok": True, **out}


@admin_router.put("/invoice-template")
def tenant_set_invoice_template_policy(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        out = service.set_invoice_template_policy(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc

    write_audit(
        db,
        action="payments.invoice_template.set",
        actor=actor,
        tenant_id=tenant_id,
        target="payments/invoice-template",
        metadata={"policy": out.get("policy")},
    )
    db.commit()
    return {"ok": True, **out}


@admin_router.post("/invoice-template/preview")
def tenant_invoice_template_preview(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        out = service.preview_invoice_document(db, tenant_id=tenant_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return out


@admin_router.get("/invoices/{invoice_id}/document")
def tenant_invoice_document(
    invoice_id: str,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    try:
        return service.get_invoice_document(db, invoice_id=invoice_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc


@super_router.get("/credit-accounts")
def super_credit_accounts(
    tenant_id: str | None = None,
    payment_mode: str | None = None,
    status: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_credit_accounts(
            db,
            tenant_id=(str(tenant_id).strip() if tenant_id else None),
            payment_mode=payment_mode,
            status=status,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.put("/credit-accounts/{tenant_id}")
def super_upsert_credit_account(
    tenant_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        item = service.upsert_credit_account(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc

    write_audit(
        db,
        action="payments.credit_account.upsert",
        actor=actor,
        tenant_id=str(item.get("tenant_id") or None),
        target=f"payments/credit-account/{tenant_id}",
        metadata={
            "payment_mode": item.get("payment_mode"),
            "status": item.get("status"),
            "credit_limit_minor": item.get("credit_limit_minor"),
            "currency": item.get("currency"),
            "terms_days": item.get("terms_days"),
            "grace_days": item.get("grace_days"),
            "overdue_hold": item.get("overdue_hold"),
        },
    )
    db.commit()
    return {"ok": True, "item": item}


@super_router.get("/invoice-template/{tenant_id}")
def super_invoice_template_policy(
    tenant_id: str,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        out = service.get_invoice_template_policy(db, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), **out}


@super_router.put("/invoice-template/{tenant_id}")
def super_set_invoice_template_policy(
    tenant_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.set_invoice_template_policy(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc

    write_audit(
        db,
        action="payments.invoice_template.set.superadmin",
        actor=actor,
        tenant_id=tenant_id,
        target=f"payments/invoice-template/{tenant_id}",
        metadata={"policy": out.get("policy")},
    )
    db.commit()
    return {"ok": True, "requested_by": actor, **out}


@super_router.get("/invoices")
def super_invoices(
    tenant_id: str | None = None,
    status: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_invoices(
            db,
            tenant_id=(str(tenant_id).strip() if tenant_id else None),
            status=status,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.get("/invoices/{invoice_id}/document")
def super_invoice_document(
    invoice_id: str,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        out = service.get_invoice_document(db, invoice_id=invoice_id, tenant_id=None)
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc
    out["requested_by"] = claims.get("sub", "unknown")
    return out


@super_router.post("/invoices/{invoice_id}/mark-paid")
def super_mark_invoice_paid(
    invoice_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.mark_invoice_paid(db, invoice_id=invoice_id, actor=actor, payload=(payload or {}))
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc

    inv = out.get("invoice") or {}
    write_audit(
        db,
        action="payments.invoice.mark_paid",
        actor=actor,
        tenant_id=inv.get("tenant_id"),
        target=f"payments/invoice/{invoice_id}",
        metadata={
            "amount_minor": inv.get("amount_minor"),
            "currency": inv.get("currency"),
            "status": inv.get("status"),
            "method": ((out.get("allocation") or {}).get("method")),
            "reference": ((out.get("allocation") or {}).get("reference")),
        },
    )
    db.commit()
    return out


@super_router.post("/overdue/run-once")
def super_run_overdue_once(
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("PAYMENTS.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    body = payload or {}
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.run_overdue_sync(
            db,
            actor=actor,
            tenant_id=(str(body.get("tenant_id") or "").strip() or None),
            limit=(int(body.get("limit") or 500)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=_err_status(str(exc)), detail=str(exc)) from exc

    write_audit(
        db,
        action="payments.overdue.run_once",
        actor=actor,
        tenant_id=(str(body.get("tenant_id") or "").strip() or None),
        target="payments/overdue/run-once",
        metadata={
            "processed": out.get("processed"),
            "marked_overdue": out.get("marked_overdue"),
            "tenants_touched": out.get("tenants_touched"),
            "accounts_updated": out.get("accounts_updated"),
        },
    )
    db.commit()
    return {"ok": True, "requested_by": actor, "result": out}