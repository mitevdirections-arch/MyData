from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_superadmin
from app.db.models import Tenant
from app.db.session import get_db_session
from app.modules.profile.user_domain_service import service as user_domain_service

router = APIRouter(prefix="/admin/tenants", tags=["tenants"])


@router.get("")
def list_tenants(claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    rows = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "items": [{"id": t.id, "name": t.name, "vat_number": t.vat_number, "is_active": t.is_active} for t in rows],
    }


@router.post("/bootstrap-demo")
def bootstrap_tenant(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    tenant_name = str(payload.get("name") or tenant_id).strip()
    vat_number = str(payload.get("vat_number") or "").strip() or None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    existing = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if existing is None:
        db.add(Tenant(id=tenant_id, name=tenant_name, vat_number=vat_number, is_active=True))
        db.commit()
    else:
        changed = False
        if tenant_name and existing.name != tenant_name:
            existing.name = tenant_name
            changed = True
        if vat_number and existing.vat_number != vat_number:
            existing.vat_number = vat_number
            changed = True
        if changed:
            db.commit()

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "created": existing is None,
        "vat_number": vat_number or (existing.vat_number if existing else None),
        "by": claims.get("sub", "unknown"),
    }

@router.post("/{tenant_id}/bootstrap-first-admin")
def bootstrap_first_tenant_admin(
    tenant_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    data = dict(payload or {})
    data["allow_if_exists"] = bool(data.get("allow_if_exists", False))

    try:
        out = user_domain_service.bootstrap_first_tenant_admin(
            db,
            tenant_id=tenant_id,
            actor=actor,
            payload=data,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "tenant_not_found" else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    db.commit()
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "requested_by": actor,
        "result": out,
    }

