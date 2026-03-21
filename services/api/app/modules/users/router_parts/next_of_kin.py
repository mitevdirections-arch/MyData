from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.users.router_parts.common import (
    _ensure_workspace_admin_or_403,
    _resolve_scope_or_400,
    _tenant_for_audit,
)
from app.modules.users.service import service as user_domain_service

router = APIRouter()


@router.get("/admin/users/{user_id}/next-of-kin")
def list_user_next_of_kin(
    user_id: str,
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = user_domain_service.list_user_next_of_kin(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=user_id,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "user_id": user_id, "items": out}


@router.post("/admin/users/{user_id}/next-of-kin")
def create_user_next_of_kin(
    user_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.upsert_user_next_of_kin(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            kin_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="users.user.next_of_kin.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-next-of-kin/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/next-of-kin/{kin_id}")
def update_user_next_of_kin(
    user_id: str,
    kin_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.upsert_user_next_of_kin(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            kin_id=kin_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"kin_not_found", "user_next_of_kin_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="users.user.next_of_kin.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-next-of-kin/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/admin/users/{user_id}/next-of-kin/{kin_id}")
def delete_user_next_of_kin(
    user_id: str,
    kin_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.delete_user_next_of_kin(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            kin_id=kin_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"kin_not_found", "user_next_of_kin_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="users.user.next_of_kin.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-next-of-kin/{wtype}/{wid}/{user_id}/{kin_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}
