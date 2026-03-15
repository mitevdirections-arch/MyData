from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claims
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.modules.licensing.deps import require_module_entitlement
from app.modules.profile.service import WORKSPACE_PLATFORM, WORKSPACE_TENANT, service as profile_service
from app.modules.support.service import service as support_service
from app.modules.public_portal.service import (
    build_editor_state,
    build_public_payload,
    create_logo_upload_slot,
    get_workspace_settings,
    mark_logo_uploaded,
    publish_draft,
    update_draft,
    update_workspace_settings,
    list_brand_assets,
)

router = APIRouter(prefix="/public", tags=["public"])
admin_router = APIRouter(
    prefix="/admin/public-profile",
    tags=["public-profile-admin"],
    dependencies=[Depends(require_module_entitlement("PUBLIC_PORTAL"))],
)


def _resolve_admin_workspace(claims: dict[str, Any], workspace: str | None, db: Session) -> tuple[str, str]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")

    try:
        wtype, wid = profile_service.resolve_workspace(claims, workspace=workspace)
        if wtype == WORKSPACE_TENANT and "SUPERADMIN" in roles:
            support_service.validate_superadmin_tenant_scope(db, claims=claims, tenant_id=wid)
        return wtype, wid
    except ValueError as exc:
        detail = str(exc)
        code = 403 if detail in {"platform_workspace_requires_superadmin", "support_session_required_for_tenant_scope", "tenant_admin_required", "support_session_invalid_or_expired"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc


def _tenant_for_audit(workspace_type: str, workspace_id: str) -> str | None:
    return workspace_id if workspace_type == WORKSPACE_TENANT else None


@router.get("/profile/{tenant_id}")
def tenant_public_profile(tenant_id: str, locale: str | None = None, db: Session = Depends(get_db_session)) -> dict:
    out = build_public_payload(
        db,
        workspace_type=WORKSPACE_TENANT,
        workspace_id=str(tenant_id or "").strip(),
        requested_locale=locale,
        page_code=get_settings().public_page_default_code,
    )
    return {"ok": True, "tenant_id": tenant_id, "published": out}


@router.get("/site/{workspace_type}/{workspace_id}")
def workspace_public_site(workspace_type: str, workspace_id: str, locale: str | None = None, db: Session = Depends(get_db_session)) -> dict:
    wtype = str(workspace_type or "").strip().upper()
    if wtype not in {WORKSPACE_TENANT, WORKSPACE_PLATFORM}:
        raise HTTPException(status_code=400, detail="workspace_type_invalid")

    out = build_public_payload(
        db,
        workspace_type=wtype,
        workspace_id=str(workspace_id or "").strip(),
        requested_locale=locale,
        page_code=get_settings().public_page_default_code,
    )
    return {"ok": True, "site": out}


@admin_router.get("/settings")
def admin_get_settings(
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    s = get_workspace_settings(db=db, workspace_type=wtype, workspace_id=wid)
    return {
        "ok": True,
        "workspace_type": wtype,
        "workspace_id": wid,
        "settings": {
            "show_company_info": bool(s.show_company_info),
            "show_fleet": bool(s.show_fleet),
            "show_contacts": bool(s.show_contacts),
            "show_price_list": bool(s.show_price_list),
            "show_working_hours": bool(s.show_working_hours),
            "updated_by": s.updated_by,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        },
    }


@admin_router.put("/settings")
def admin_put_settings(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")

    s = update_workspace_settings(db=db, workspace_type=wtype, workspace_id=wid, payload=payload, actor=actor)
    write_audit(
        db,
        action="public_profile.settings_update",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"public_profile/settings/{wtype}/{wid}",
        metadata={
            "workspace_type": wtype,
            "workspace_id": wid,
            "show_company_info": bool(s.show_company_info),
            "show_fleet": bool(s.show_fleet),
            "show_contacts": bool(s.show_contacts),
            "show_price_list": bool(s.show_price_list),
            "show_working_hours": bool(s.show_working_hours),
        },
    )
    db.commit()

    return {
        "ok": True,
        "workspace_type": wtype,
        "workspace_id": wid,
        "settings": {
            "show_company_info": bool(s.show_company_info),
            "show_fleet": bool(s.show_fleet),
            "show_contacts": bool(s.show_contacts),
            "show_price_list": bool(s.show_price_list),
            "show_working_hours": bool(s.show_working_hours),
        },
    }


@admin_router.get("/editor")
def editor_state(
    workspace: str | None = None,
    locale: str | None = None,
    page_code: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    out = build_editor_state(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        locale=str(locale or get_settings().public_page_default_locale),
        page_code=str(page_code or get_settings().public_page_default_code).strip().upper(),
        actor=actor,
    )
    return {"ok": True, **out}


@admin_router.put("/editor/draft")
def editor_update_draft(
    payload: dict[str, Any],
    workspace: str | None = None,
    locale: str | None = None,
    page_code: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    loc = str(locale or get_settings().public_page_default_locale)
    pcode = str(page_code or get_settings().public_page_default_code).strip().upper()

    try:
        row = update_draft(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            locale=loc,
            page_code=pcode,
            payload=payload,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="public_profile.draft_update",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"public_profile/draft/{wtype}/{wid}/{loc}/{pcode}",
        metadata={"workspace_type": wtype, "workspace_id": wid, "locale": loc, "page_code": pcode},
    )
    db.commit()
    return {
        "ok": True,
        "draft": {
            "id": str(row.id),
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "locale": row.locale,
            "page_code": row.page_code,
            "content": row.content_json or {},
            "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@admin_router.post("/editor/publish")
def editor_publish(
    payload: dict[str, Any] | None = None,
    workspace: str | None = None,
    locale: str | None = None,
    page_code: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    body = payload or {}
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    loc = str(locale or get_settings().public_page_default_locale)
    pcode = str(page_code or get_settings().public_page_default_code).strip().upper()

    row = publish_draft(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        locale=loc,
        page_code=pcode,
        actor=actor,
        note=str(body.get("note") or "").strip() or None,
    )

    write_audit(
        db,
        action="public_profile.publish",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"public_profile/publish/{wtype}/{wid}/{loc}/{pcode}",
        metadata={"workspace_type": wtype, "workspace_id": wid, "locale": loc, "page_code": pcode, "version": int(row.version)},
    )
    db.commit()

    return {
        "ok": True,
        "published": {
            "id": str(row.id),
            "workspace_type": row.workspace_type,
            "workspace_id": row.workspace_id,
            "locale": row.locale,
            "page_code": row.page_code,
            "version": int(row.version),
            "publish_note": row.publish_note,
            "published_by": row.published_by,
            "published_at": row.published_at.isoformat() if row.published_at else None,
        },
    }


@admin_router.get("/editor/preview")
def editor_preview(
    workspace: str | None = None,
    locale: str | None = None,
    page_code: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    loc = str(locale or get_settings().public_page_default_locale)
    pcode = str(page_code or get_settings().public_page_default_code).strip().upper()

    state = build_editor_state(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        locale=loc,
        page_code=pcode,
        actor=actor,
    )
    return {
        "ok": True,
        "workspace_type": wtype,
        "workspace_id": wid,
        "locale": loc,
        "page_code": pcode,
        "preview": (state.get("draft") or {}).get("content") or {},
        "published": state.get("published"),
    }


@admin_router.post("/assets/logo/presign-upload")
def logo_presign_upload(
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")

    try:
        slot = create_logo_upload_slot(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            actor=actor,
            file_name=str(payload.get("file_name") or "").strip(),
            content_type=str(payload.get("content_type") or "").strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="public_profile.logo_presign_upload",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"public_profile/logo/{slot.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid, "asset_kind": "LOGO"},
    )
    db.commit()
    return {"ok": True, "slot": slot}


@admin_router.post("/assets/{asset_id}/mark-uploaded")
def logo_mark_uploaded(
    asset_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")

    try:
        item = mark_logo_uploaded(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            asset_id=asset_id,
            size_bytes=int(payload.get("size_bytes") or 0),
            sha256=str(payload.get("sha256") or "").strip(),
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "public_asset_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="public_profile.logo_uploaded",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"public_profile/logo/{asset_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid, "asset_kind": "LOGO", "status": item.get("status")},
    )
    db.commit()
    return {"ok": True, "item": item}


@admin_router.get("/assets")
def assets_list(
    workspace: str | None = None,
    asset_kind: str = "LOGO",
    limit: int = 100,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict:
    wtype, wid = _resolve_admin_workspace(claims, workspace, db)
    items = list_brand_assets(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        asset_kind=asset_kind,
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "items": items}