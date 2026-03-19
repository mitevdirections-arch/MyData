from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.core.permissions import list_permission_registry, list_role_templates
from app.core.rls import bind_rls_context, rls_context_from_claims
from app.db.session import get_db_session
from app.modules.iam.service import service

router = APIRouter(prefix="/iam", tags=["iam"])


@router.get("/permission-registry")
def permission_registry(
    workspace: str | None = None,
    module_code: str | None = None,
    include_inactive: bool = False,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
) -> dict[str, Any]:
    try:
        wtype, wid = service._resolve_scope(claims, workspace)
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail in {"platform_workspace_requires_superadmin", "support_session_required_for_tenant_scope", "tenant_admin_required"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    items = list_permission_registry(workspace_type=wtype, module_code=module_code, include_inactive=include_inactive)
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": items}


@router.get("/role-templates")
def role_templates(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
) -> dict[str, Any]:
    try:
        wtype, wid = service._resolve_scope(claims, workspace)
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail in {"platform_workspace_requires_superadmin", "support_session_required_for_tenant_scope", "tenant_admin_required"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    items = list_role_templates(workspace_type=wtype)
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": items}


@router.get("/me/access")
def me_access(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        out = service.me_access(db, claims=claims, workspace=workspace)
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail in {"platform_workspace_requires_superadmin", "support_session_required_for_tenant_scope", "tenant_admin_required"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc
    return {"ok": True, **out}


@router.post("/me/access/check")
def me_access_check(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    bind_rls_context(db, claims)
    try:
        out = service.check_permission(
            db,
            claims=claims,
            workspace=workspace,
            permission_code=str(payload.get("permission_code") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="iam.permission_check",
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=(out.get("workspace_id") if out.get("workspace_type") == "TENANT" else None),
        target=f"iam/check/{out.get('permission_code')}",
        metadata={"allowed": out.get("allowed"), "workspace_type": out.get("workspace_type")},
    )
    db.commit()
    return {"ok": True, **out}


@router.get("/admin/rls-context")
def admin_rls_context(claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ"))) -> dict[str, Any]:
    return {"ok": True, "context": rls_context_from_claims(claims)}
