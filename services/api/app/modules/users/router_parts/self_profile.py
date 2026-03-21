from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.profile.service import service as profile_service
from app.modules.users.router_parts.common import _resolve_scope_or_400, _tenant_for_audit


def profile_me(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = profile_service.get_or_create_admin_profile(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=str(claims.get("sub") or ""),
        actor=str(claims.get("sub") or "unknown"),
    )
    return {"ok": True, "profile": out}


def profile_me_update(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = profile_service.update_admin_profile(
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
