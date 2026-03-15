from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin, require_tenant_admin
from app.db.session import get_db_session
from app.modules.incidents import service
from app.modules.licensing.deps import require_module_entitlement

admin_router = APIRouter(
    prefix="/admin/incidents",
    tags=["admin.incidents"],
    dependencies=[Depends(require_module_entitlement("INCIDENTS"))],
)
super_router = APIRouter(prefix="/superadmin/incidents", tags=["superadmin.incidents"])


@admin_router.post("")
def create_incident(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        row = service.create_incident(
            db,
            tenant_id=tenant_id,
            created_by=actor,
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            severity=str(payload.get("severity") or "MEDIUM"),
            category=str(payload.get("category") or "OTHER"),
            source=str(payload.get("source") or "TENANT"),
            evidence_object_ids=list(payload.get("evidence_object_ids") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="incident.created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"incident/{row.id}",
        metadata={"severity": row.severity, "category": row.category, "source": row.source},
    )
    db.commit()
    return {"ok": True, "item": service.to_dict(row)}


@admin_router.get("")
def list_my_incidents(status: str | None = None, limit: int = 100, claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        rows = service.list_incidents_for_tenant(db, tenant_id=tenant_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "items": [service.to_dict(x) for x in rows]}


@admin_router.get("/{incident_id}")
def get_my_incident(incident_id: str, claims: dict[str, Any] = Depends(require_tenant_admin), db: Session = Depends(get_db_session)) -> dict:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    row = service.get_incident_for_tenant(db, tenant_id=tenant_id, incident_id=incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="incident_not_found")
    return {"ok": True, "item": service.to_dict(row)}


@super_router.get("")
def list_global_incidents(
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    try:
        rows = service.list_incidents_global(db, status=status, tenant_id=tenant_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": [service.to_dict(x) for x in rows]}


@super_router.post("/{incident_id}/ack")
def ack_incident(incident_id: str, claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict:
    actor = str(claims.get("sub") or "unknown")
    try:
        row = service.acknowledge_incident(db, incident_id=incident_id, actor=actor)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "incident_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="incident.acknowledged",
        actor=actor,
        tenant_id=row.tenant_id,
        target=f"incident/{row.id}",
        metadata={"status": row.status},
    )
    db.commit()
    return {"ok": True, "item": service.to_dict(row)}


@super_router.post("/{incident_id}/resolve")
def resolve_incident(incident_id: str, payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict:
    actor = str(claims.get("sub") or "unknown")
    try:
        row = service.resolve_incident(
            db,
            incident_id=incident_id,
            actor=actor,
            resolution_note=str(payload.get("resolution_note") or "").strip() or None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "incident_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="incident.resolved",
        actor=actor,
        tenant_id=row.tenant_id,
        target=f"incident/{row.id}",
        metadata={"status": row.status},
    )
    db.commit()
    return {"ok": True, "item": service.to_dict(row)}
