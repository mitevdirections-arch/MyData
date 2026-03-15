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
@router.get("/admin/roles")
def list_roles(
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.list_roles(db, workspace_type=wtype, workspace_id=wid, actor=str(claims.get("sub") or "unknown"), limit=limit)
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": out}


@router.put("/admin/roles/{role_code}")
def upsert_role(
    role_code: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_role(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            role_code=role_code,
            payload=payload,
            actor=actor,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail == "system_role_read_only" else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.role.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"role/{wtype}/{wid}/{out.get('role_code')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users")
def list_users(
    workspace: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = service.list_workspace_users(db, workspace_type=wtype, workspace_id=wid, actor=str(claims.get("sub") or "unknown"), limit=limit)
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": out}


@router.put("/admin/users/{user_id}")
def upsert_user(
    user_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_workspace_user(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            payload=payload,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user/{wtype}/{wid}/{user_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users/{user_id}")
def get_user(
    user_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    try:
        out = service.get_workspace_user(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=str(claims.get("sub") or "unknown"),
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "workspace_user_not_found" else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/roles")
def set_user_roles(
    user_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.set_workspace_user_roles(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            role_codes=list(payload.get("role_codes") or []),
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.roles.set",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-roles/{wtype}/{wid}/{user_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid, "roles": out.get("roles")},
    )
    db.commit()
    return {"ok": True, "item": out}


