from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission, require_superadmin_permission, require_tenant_admin_permission
from app.db.session import get_db_session
from app.modules.i18n.service import service
from app.modules.profile.service import PLATFORM_WORKSPACE_ID, WORKSPACE_PLATFORM, WORKSPACE_TENANT

router = APIRouter(prefix="/i18n", tags=["i18n"])
admin_router = APIRouter(prefix="/admin/i18n", tags=["admin.i18n"])
super_router = APIRouter(prefix="/superadmin/i18n", tags=["superadmin.i18n"])


@router.get("/locales")
def locales() -> dict[str, Any]:
    return {"ok": True, "items": service.list_locales()}


@router.get("/catalog/{locale}")
def catalog(locale: str) -> dict[str, Any]:
    return service.get_catalog(locale)


@router.get("/effective")
def effective_locale(
    workspace: str | None = None,
    locale: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("I18N.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return service.resolve_effective_locale(db, claims=claims, workspace=workspace, requested_locale=locale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.get("/tenant-default")
def tenant_default_get(claims: dict[str, Any] = Depends(require_tenant_admin_permission("I18N.READ")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    out = service.get_workspace_policy(
        db,
        workspace_type=WORKSPACE_TENANT,
        workspace_id=tenant_id,
    )
    return {"ok": True, "policy": out}


@admin_router.put("/tenant-default")
def tenant_default_put(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin_permission("I18N.WRITE")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.set_workspace_policy(
            db,
            workspace_type=WORKSPACE_TENANT,
            workspace_id=tenant_id,
            actor=actor,
            default_locale=str(payload.get("default_locale") or "en"),
            fallback_locale=str(payload.get("fallback_locale") or "en"),
            enabled_locales=list(payload.get("enabled_locales") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="i18n.tenant_policy.updated",
        actor=actor,
        tenant_id=tenant_id,
        target="i18n/tenant-default",
        metadata={
            "default_locale": out.get("default_locale"),
            "fallback_locale": out.get("fallback_locale"),
            "enabled_locales": out.get("enabled_locales"),
        },
    )
    db.commit()
    return {"ok": True, "policy": out}


@super_router.get("/platform-default")
def platform_default_get(claims: dict[str, Any] = Depends(require_superadmin_permission("I18N.READ")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    out = service.get_workspace_policy(
        db,
        workspace_type=WORKSPACE_PLATFORM,
        workspace_id=PLATFORM_WORKSPACE_ID,
    )
    return {"ok": True, "policy": out}


@super_router.put("/platform-default")
def platform_default_put(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_superadmin_permission("I18N.WRITE")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.set_workspace_policy(
            db,
            workspace_type=WORKSPACE_PLATFORM,
            workspace_id=PLATFORM_WORKSPACE_ID,
            actor=actor,
            default_locale=str(payload.get("default_locale") or "en"),
            fallback_locale=str(payload.get("fallback_locale") or "en"),
            enabled_locales=list(payload.get("enabled_locales") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="i18n.platform_policy.updated",
        actor=actor,
        tenant_id=None,
        target="i18n/platform-default",
        metadata={
            "default_locale": out.get("default_locale"),
            "fallback_locale": out.get("fallback_locale"),
            "enabled_locales": out.get("enabled_locales"),
        },
    )
    db.commit()
    return {"ok": True, "policy": out}