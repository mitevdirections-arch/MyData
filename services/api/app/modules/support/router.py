from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin_permission, require_tenant_admin_permission
from app.db.session import get_db_session
from app.modules.support.service import service


tenant_router = APIRouter(prefix="/support/tenant", tags=["support.tenant"])
super_router = APIRouter(prefix="/support/superadmin", tags=["support.superadmin"])
public_router = APIRouter(prefix="/support/public", tags=["support.public"])


def _support_error_to_status(detail: str) -> int:
    if detail in {"support_request_not_found", "support_session_not_found", "support_faq_not_found"}:
        return 404
    if detail in {"missing_tenant_context", "support_session_required_for_tenant_scope"}:
        return 403
    return 400


@tenant_router.post("/requests")
def tenant_create_request(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.WRITE")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.create_request(db, tenant_id=tenant_id, actor=actor, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="support.request.created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"support/request/{out.get('id')}",
        metadata={"channel": out.get("channel"), "priority": out.get("priority"), "status": out.get("status")},
    )
    db.commit()
    return {"ok": True, "item": out}


@tenant_router.get("/requests")
def tenant_list_requests(status: str | None = None, limit: int = 200, claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.READ")), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        items = service.list_tenant_requests(db, tenant_id=tenant_id, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "items": items}


@tenant_router.post("/requests/{request_id}/open-door")
def tenant_open_door(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    body = payload or {}
    try:
        out = service.open_door(
            db,
            request_id=request_id,
            tenant_id=tenant_id,
            actor=actor,
            door_open_minutes=(body.get("door_open_minutes") if "door_open_minutes" in body else None),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.request.door_opened",
        actor=actor,
        tenant_id=tenant_id,
        target=f"support/request/{request_id}",
        metadata={"status": out.get("status"), "door_expires_at": out.get("door_expires_at")},
    )
    db.commit()
    return {"ok": True, "item": out}


@tenant_router.post("/requests/{request_id}/close")
def tenant_close_request(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    body = payload or {}
    try:
        out = service.close_request(
            db,
            request_id=request_id,
            tenant_id=tenant_id,
            actor=actor,
            reason=str(body.get("reason") or "").strip() or None,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.request.closed",
        actor=actor,
        tenant_id=tenant_id,
        target=f"support/request/{request_id}",
        metadata={"status": out.get("status"), "close_reason": out.get("close_reason")},
    )
    db.commit()
    return {"ok": True, "item": out}


@tenant_router.get("/requests/{request_id}/messages")
def tenant_list_messages(
    request_id: str,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        items = service.list_messages(db, request_id=request_id, tenant_id=tenant_id, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    return {"ok": True, "items": items}


@tenant_router.post("/requests/{request_id}/messages")
def tenant_add_message(
    request_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.add_tenant_message(db, tenant_id=tenant_id, request_id=request_id, actor=actor, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.message.tenant_created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"support/request/{request_id}",
        metadata={"message_id": out.get("id"), "channel": out.get("channel")},
    )
    db.commit()
    return {"ok": True, "item": out}


@tenant_router.post("/requests/{request_id}/chat-bot")
def tenant_chat_bot(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_tenant_admin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    body = payload or {}
    try:
        out = service.bot_reply(
            db,
            tenant_id=tenant_id,
            request_id=request_id,
            actor="support-bot",
            prompt=(str(body.get("prompt") or "").strip() or None),
            locale=(str(body.get("locale") or "").strip() or None),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.message.bot_generated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"support/request/{request_id}",
        metadata={"message_id": (out.get("message") or {}).get("id")},
    )
    db.commit()
    return {"ok": True, **out}


@super_router.get("/requests")
def super_list_requests(
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_super_requests(db, status=status, tenant_id=tenant_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.post("/requests/{request_id}/start-session")
def super_start_session(
    request_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    try:
        out = service.start_session(
            db,
            request_id=request_id,
            actor=actor,
            ttl_minutes=(body.get("ttl_minutes") if "ttl_minutes" in body else None),
            capabilities=list(body.get("capabilities") or []),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.session.started",
        actor=actor,
        tenant_id=(out.get("request") or {}).get("tenant_id"),
        target=f"support/session/{(out.get('session') or {}).get('id')}",
        metadata={"request_id": request_id, "expires_at": (out.get("session") or {}).get("expires_at")},
    )
    db.commit()
    return {"ok": True, **out}


@super_router.get("/sessions")
def super_list_sessions(
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_sessions(db, status=status, tenant_id=tenant_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.post("/sessions/{session_id}/end")
def super_end_session(
    session_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    try:
        out = service.end_session(
            db,
            session_id=session_id,
            actor=actor,
            reason=str(body.get("reason") or "").strip() or None,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.session.ended",
        actor=actor,
        tenant_id=out.get("tenant_id"),
        target=f"support/session/{session_id}",
        metadata={"status": out.get("status"), "end_reason": out.get("end_reason")},
    )
    db.commit()
    return {"ok": True, "session": out}


@super_router.post("/sessions/{session_id}/issue-token")
def super_issue_scoped_token(
    session_id: str,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.issue_session_token(db, session_id=session_id, actor=actor)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.session.token_issued",
        actor=actor,
        tenant_id=out.get("tenant_id"),
        target=f"support/session/{session_id}",
        metadata={"expires_in_seconds": out.get("expires_in_seconds")},
    )
    db.commit()
    return out


@super_router.get("/requests/{request_id}/messages")
def super_list_messages(
    request_id: str,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_messages(db, request_id=request_id, tenant_id=None, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.post("/requests/{request_id}/messages")
def super_add_message(
    request_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.add_superadmin_message(db, request_id=request_id, actor=actor, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.message.superadmin_created",
        actor=actor,
        tenant_id=out.get("tenant_id"),
        target=f"support/request/{request_id}",
        metadata={"message_id": out.get("id"), "channel": out.get("channel")},
    )
    db.commit()
    return {"ok": True, "item": out}


@super_router.get("/faq")
def super_list_faq(
    status: str | None = None,
    locale: str | None = None,
    limit: int = 300,
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_admin_faq(db, status=status, locale=locale, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    db.commit()
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "items": items}


@super_router.post("/faq")
def super_create_faq(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_faq_entry(db, actor=actor, payload=payload)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.faq.created",
        actor=actor,
        tenant_id="superadmin",
        target=f"support/faq/{out.get('id')}",
        metadata={"locale": out.get("locale"), "status": out.get("status")},
    )
    db.commit()
    return {"ok": True, "item": out}


@super_router.put("/faq/{entry_id}")
def super_update_faq(
    entry_id: str,
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin_permission("SUPPORT.WRITE")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.upsert_faq_entry(db, actor=actor, payload=payload, entry_id=entry_id)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="support.faq.updated",
        actor=actor,
        tenant_id="superadmin",
        target=f"support/faq/{entry_id}",
        metadata={"locale": out.get("locale"), "status": out.get("status")},
    )
    db.commit()
    return {"ok": True, "item": out}


@public_router.get("/faq")
def public_list_faq(
    locale: str | None = None,
    q: str | None = None,
    category: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_public_faq(db, locale=locale, q=q, category=category, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_support_error_to_status(detail), detail=detail) from exc

    db.commit()
    return {"ok": True, "items": items}