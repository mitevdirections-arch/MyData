from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claim_permission
from app.db.session import get_db_session
from app.modules.profile.router_parts.common import (
    _ensure_workspace_admin_or_403,
    _resolve_scope_or_400,
    _tenant_for_audit,
)
from app.modules.profile.user_domain_service import service as user_domain_service

router = APIRouter()
@router.get("/admin/users/{user_id}/profile")
def get_user_profile(
    user_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    try:
        out = user_domain_service.get_or_create_user_profile(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=str(claims.get("sub") or "unknown"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/profile")
def update_user_profile(
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
        out = user_domain_service.update_user_profile(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.profile.update",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-profile/{wtype}/{wid}/{user_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users/{user_id}/contacts")
def list_user_contacts(
    user_id: str,
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = user_domain_service.list_user_contacts(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=user_id,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "user_id": user_id, "items": out}


@router.post("/admin/users/{user_id}/contacts")
def create_user_contact(
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
        out = user_domain_service.upsert_user_contact(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            contact_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.contact.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-contact/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/contacts/{contact_id}")
def update_user_contact(
    user_id: str,
    contact_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.upsert_user_contact(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
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
        action="profile.user.contact.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-contact/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/admin/users/{user_id}/contacts/{contact_id}")
def delete_user_contact(
    user_id: str,
    contact_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.delete_user_contact(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            contact_id=contact_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"contact_not_found", "user_contact_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.contact.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-contact/{wtype}/{wid}/{user_id}/{contact_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users/{user_id}/addresses")
def list_user_addresses(
    user_id: str,
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = user_domain_service.list_user_addresses(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=user_id,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "user_id": user_id, "items": out}


@router.post("/admin/users/{user_id}/addresses")
def create_user_address(
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
        out = user_domain_service.upsert_user_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            address_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.address.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-address/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/addresses/{address_id}")
def update_user_address(
    user_id: str,
    address_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.upsert_user_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
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
        action="profile.user.address.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-address/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/admin/users/{user_id}/addresses/{address_id}")
def delete_user_address(
    user_id: str,
    address_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.delete_user_address(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            address_id=address_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"address_not_found", "user_address_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.address.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-address/{wtype}/{wid}/{user_id}/{address_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users/{user_id}/documents")
def list_user_documents(
    user_id: str,
    workspace: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    out = user_domain_service.list_user_documents(
        db,
        workspace_type=wtype,
        workspace_id=wid,
        user_id=user_id,
        actor=str(claims.get("sub") or "unknown"),
        limit=limit,
    )
    return {"ok": True, "workspace_type": wtype, "workspace_id": wid, "user_id": user_id, "items": out}


@router.post("/admin/users/{user_id}/documents")
def create_user_document(
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
        out = user_domain_service.upsert_user_document(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            document_id=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="profile.user.document.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-document/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.put("/admin/users/{user_id}/documents/{document_id}")
def update_user_document(
    user_id: str,
    document_id: str,
    payload: dict[str, Any],
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.upsert_user_document(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            document_id=document_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"document_not_found", "user_document_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.document.upsert",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-document/{wtype}/{wid}/{user_id}/{out.get('id')}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.delete("/admin/users/{user_id}/documents/{document_id}")
def delete_user_document(
    user_id: str,
    document_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    actor = str(claims.get("sub") or "unknown")
    try:
        out = user_domain_service.delete_user_document(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            document_id=document_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail in {"document_not_found", "user_document_not_found"} else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.document.delete",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-document/{wtype}/{wid}/{user_id}/{document_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.get("/admin/users/{user_id}/credentials")
def get_user_credentials(
    user_id: str,
    workspace: str | None = None,
    claims: dict[str, Any] = Depends(require_claim_permission("IAM.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_workspace_admin_or_403(claims)
    wtype, wid = _resolve_scope_or_400(claims, workspace, db)
    try:
        out = user_domain_service.get_user_credential(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=str(claims.get("sub") or "unknown"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": out}


@router.post("/admin/users/{user_id}/credentials/issue")
def issue_user_credentials(
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
        out = user_domain_service.issue_user_credentials(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
            reset_existing=False,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "workspace_user_not_found" else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.credentials.issue",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-credentials/{wtype}/{wid}/{user_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return out


@router.post("/admin/users/{user_id}/credentials/reset-password")
def reset_user_password(
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
        out = user_domain_service.reset_user_password(
            db,
            workspace_type=wtype,
            workspace_id=wid,
            user_id=user_id,
            actor=actor,
            payload=payload,
        )
    except ValueError as exc:
        detail = str(exc)
        code = 404 if detail == "workspace_user_not_found" else 400
        raise HTTPException(status_code=code, detail=detail) from exc

    write_audit(
        db,
        action="profile.user.credentials.reset",
        actor=actor,
        tenant_id=_tenant_for_audit(wtype, wid),
        target=f"user-credentials/{wtype}/{wid}/{user_id}",
        metadata={"workspace_type": wtype, "workspace_id": wid},
    )
    db.commit()
    return out


