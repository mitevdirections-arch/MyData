from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.users.router_parts.common import _resolve_scope_or_400, _tenant_for_audit
from app.modules.users.service import service as user_domain_service


def _self_credential_error_status(detail: str) -> int:
    if detail in {"tenant_not_found", "user_membership_required", "credential_not_found"}:
        return 404
    if detail in {"current_password_invalid", "invite_token_invalid"}:
        return 403
    if detail in {
        "credential_disabled",
        "credential_not_active",
        "credential_locked",
        "invite_not_accepted",
        "invite_not_pending",
        "invite_expired",
        "new_password_reuse_not_allowed",
        "username_not_available",
    }:
        return 409
    return 400


def change_my_password(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "").strip()
    if not actor:
        raise HTTPException(status_code=400, detail="sub_required")
    try:
        out = user_domain_service.change_my_password(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=actor,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_self_credential_error_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="users.me.credentials.password.change",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-credentials/{wtype}/{wid}/{actor}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return out


def change_my_username(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("PROFILE.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "").strip()
    if not actor:
        raise HTTPException(status_code=400, detail="sub_required")
    try:
        out = user_domain_service.change_my_username(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=actor,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_self_credential_error_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="users.me.credentials.username.change",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-credentials/{wtype}/{wid}/{actor}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return out

