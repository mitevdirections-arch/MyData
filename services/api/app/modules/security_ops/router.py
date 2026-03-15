from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_superadmin
from app.db.session import get_db_session
from app.modules.security_ops.service import service

router = APIRouter(prefix="/superadmin/security", tags=["superadmin.security"])


def _err_status(detail: str) -> int:
    if detail in {"security_alert_not_found", "tenant_not_found"}:
        return 404
    if detail in {"security_alert_id_invalid", "security_alert_status_invalid", "security_event_severity_invalid", "tenant_id_required"}:
        return 400
    return 400


@router.get("/posture")
def security_posture(claims: dict[str, Any] = Depends(require_superadmin)) -> dict[str, Any]:
    out = service.posture()
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), **out}


@router.get("/keys/lifecycle")
def security_keys_lifecycle(claims: dict[str, Any] = Depends(require_superadmin)) -> dict[str, Any]:
    out = service.key_lifecycle()
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), **out}


@router.post("/kill-switch/tenant/{tenant_id}")
def security_kill_switch_tenant(
    tenant_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    reason = str(body.get("reason") or "").strip() or None
    try:
        out = service.emergency_lock_tenant(db, tenant_id=tenant_id, actor=actor, reason=reason)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="security.kill_switch.tenant_locked",
        actor=actor,
        tenant_id=str(out.get("tenant_id") or tenant_id),
        target=f"security/kill-switch/{tenant_id}",
        metadata={
            "suspended_licenses": int(out.get("suspended_licenses") or 0),
            "revoked_bot_credentials": int(out.get("revoked_bot_credentials") or 0),
            "incident_id": out.get("incident_id"),
            "reason": out.get("reason"),
        },
    )
    db.commit()
    return out


@router.get("/events")
def list_security_events(
    tenant_id: str | None = None,
    severity: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_security_events(db, tenant_id=tenant_id, severity=severity, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "filters": {"tenant_id": tenant_id, "severity": severity, "limit": int(limit)},
        "summary": {"total": len(items)},
        "items": items,
    }


@router.post("/alerts/test-incident")
def security_test_incident(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    out = service.create_test_incident_and_queue(db, tenant_id=tenant_id, actor=actor, payload=payload)
    write_audit(
        db,
        action="security.alert.test_incident_created",
        actor=actor,
        tenant_id=tenant_id,
        target=f"incident/{(out.get('incident') or {}).get('id')}",
        metadata={"alert_id": ((out.get("queued_alert") or {}).get("id"))},
    )
    db.commit()
    return {"ok": True, **out}


@router.get("/alerts/queue")
def list_alert_queue(
    status: str | None = None,
    tenant_id: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        items = service.list_alert_queue(db, status=status, tenant_id=tenant_id, limit=limit)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "filters": {"status": status, "tenant_id": tenant_id, "limit": limit},
        "summary": {"total": len(items)},
        "items": items,
    }


@router.post("/alerts/dispatch-once")
def dispatch_once(
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    out = service.dispatch_once(db, actor=actor, limit=limit)
    write_audit(
        db,
        action="security.alert.dispatch_once",
        actor=actor,
        tenant_id="superadmin",
        target="security/alerts/dispatch",
        metadata={"result": out},
    )
    db.commit()
    return {"ok": True, "requested_by": actor, "result": out}


@router.post("/alerts/{alert_id}/requeue")
def requeue_alert(
    alert_id: str,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        out = service.requeue(db, alert_id=alert_id, actor=actor)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="security.alert.requeued",
        actor=actor,
        tenant_id=out.get("tenant_id"),
        target=f"security/alert/{alert_id}",
        metadata={"status": out.get("status")},
    )
    db.commit()
    return {"ok": True, "item": out}


@router.post("/alerts/{alert_id}/fail-now")
def fail_now_alert(
    alert_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    body = payload or {}
    try:
        out = service.fail_now(db, alert_id=alert_id, actor=actor, reason=str(body.get("reason") or "").strip() or None)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_err_status(detail), detail=detail) from exc

    write_audit(
        db,
        action="security.alert.failed_by_operator",
        actor=actor,
        tenant_id=out.get("tenant_id"),
        target=f"security/alert/{alert_id}",
        metadata={"status": out.get("status"), "last_error": out.get("last_error")},
    )
    db.commit()
    return {"ok": True, "item": out}