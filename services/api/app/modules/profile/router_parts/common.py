from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.profile.service import WORKSPACE_TENANT, service
from app.modules.support.service import service as support_service


def _resolve_scope_or_400(claims: dict[str, Any], workspace: str | None, db: Session) -> tuple[str, str]:
    try:
        wtype, wid = service.resolve_workspace(claims, workspace=workspace)
        roles = set(claims.get("roles") or [])
        if wtype == WORKSPACE_TENANT and "SUPERADMIN" in roles:
            support_service.validate_superadmin_tenant_scope(db, claims=claims, tenant_id=wid)
        return wtype, wid
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail in {"platform_workspace_requires_superadmin", "support_session_required_for_tenant_scope", "tenant_admin_required", "support_session_invalid_or_expired"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc


def _tenant_for_audit(workspace_type: str, workspace_id: str) -> str | None:
    return workspace_id if workspace_type == WORKSPACE_TENANT else None


def _ensure_workspace_admin_or_403(claims: dict[str, Any]) -> None:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")
