from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.profile.service import service
from app.modules.profile.router_parts.common import (
    _ensure_workspace_admin_or_403,
    _resolve_scope_or_400,
    _tenant_for_audit,
)

router = APIRouter()
@router.get("/me")
def profile_me(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.get_or_create_admin_profile(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=str(claims.get("sub") or ""),
        actor=str(claims.get("sub") or "unknown"),
    )
    return {"ok": True, "profile": out}


@router.put("/me")
def profile_me_update(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.update_admin_profile(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=actor,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.me.updated",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"profile/{wtype}/{wid}/{actor}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "profile": out}


@router.get("/workspace")
def workspace_profile_get(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.get_or_create_organization_profile(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        actor=str(claims.get("sub") or "unknown"),
    )
    return {"ok": True, "workspace_profile": out}


@router.put("/workspace")
def workspace_profile_update(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.update_organization_profile(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.workspace.updated",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-profile/{wtype}/{wid}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "workspace_profile": out}



@router.get("/workspace/contacts")
def workspace_contacts_list(
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.list_contact_points(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": out}


@router.post("/workspace/contacts")
def workspace_contacts_create(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_contact_point(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            payload=payload,
            contact_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.workspace.contact.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-contact/{wtype}/{wid}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/workspace/contacts/{contact_id}")
def workspace_contacts_update(
    contact_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_contact_point(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            payload=payload,
            contact_id=contact_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"contact_not_found", "user_contact_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.workspace.contact.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-contact/{wtype}/{wid}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/workspace/contacts/{contact_id}")
def workspace_contacts_delete(
    contact_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.delete_contact_point(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            contact_id=contact_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"contact_not_found", "user_contact_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.workspace.contact.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-contact/{wtype}/{wid}/{contact_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/workspace/addresses")
def workspace_addresses_list(
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.list_addresses(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": out}


@router.post("/workspace/addresses")
def workspace_addresses_create(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            payload=payload,
            address_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.workspace.address.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-address/{wtype}/{wid}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/workspace/addresses/{address_id}")
def workspace_addresses_update(
    address_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            payload=payload,
            address_id=address_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"address_not_found", "user_address_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.workspace.address.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-address/{wtype}/{wid}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/workspace/addresses/{address_id}")
def workspace_addresses_delete(
    address_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.delete_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            address_id=address_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"address_not_found", "user_address_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.workspace.address.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"workspace-address/{wtype}/{wid}/{address_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}

