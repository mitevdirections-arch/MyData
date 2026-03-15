from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import list_audit, verify_audit_chain, write_audit
from app.core.auth import require_claims, require_superadmin, require_tenant_admin
from app.db.session import get_db_session
from app.modules.guard.deps import require_guard_bot_signature
from app.modules.guard.service import service

router = APIRouter(prefix="/guard", tags=["guard"])


@router.post("/heartbeat")
def heartbeat(
    payload: dict[str, Any],
    _bot_sig: dict[str, Any] = Depends(require_guard_bot_signature),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id_required")

    status_val = str(payload.get("status") or "OK").upper()
    event_val = str(payload.get("event") or "KEEPALIVE").upper()
    flags = payload.get("flags") if isinstance(payload.get("flags"), dict) else {}

    if payload.get("suspected_abuse") is True:
        flags["suspected_abuse"] = True
    if payload.get("session_end") is True:
        flags["session_end"] = True

    try:
        out = service.ingest(
            db=db,
            tenant_id=tenant_id,
            device_id=device_id,
            user_id=str(claims.get("sub") or "").strip() or None,
            status=status_val,
            event=event_val,
            flags=flags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="guard.heartbeat",
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target=f"device/{device_id}",
        metadata={
            "status": status_val,
            "event": event_val,
            "flags": flags,
            "next_due_at": out.get("heartbeat_policy", {}).get("next_heartbeat_due_at"),
            "interval_seconds": out.get("heartbeat_policy", {}).get("recommended_interval_seconds"),
        },
    )
    db.commit()
    return out


@router.get("/heartbeat/policy")
def heartbeat_policy(claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "policy": service.get_behavior_policy(db, tenant_id=tenant_id),
    }


@router.post("/license-snapshot")
def license_snapshot(
    payload: dict[str, Any],
    _bot_sig: dict[str, Any] = Depends(require_guard_bot_signature),
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    device_id = str(payload.get("device_id") or "").strip()
    raw_codes = payload.get("active_license_codes")

    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id_required")
    if not isinstance(raw_codes, list):
        raise HTTPException(status_code=400, detail="active_license_codes_required")

    try:
        out = service.verify_license_snapshot(
            db,
            tenant_id=tenant_id,
            actor=actor,
            device_id=device_id,
            active_license_codes=list(raw_codes),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="guard.license_snapshot",
        actor=actor,
        tenant_id=tenant_id,
        target=f"device/{device_id}",
        metadata={
            "ok": bool(out.get("ok")),
            "unknown_codes": len(out.get("unknown_codes") or []),
            "missing_issued_codes": len(out.get("missing_issued_codes") or []),
            "client_codes_count": int(out.get("client_codes_count") or 0),
            "issued_active_count": int(out.get("issued_active_count") or 0),
            "core_present_in_client_snapshot": bool(out.get("core_present_in_client_snapshot")),
        },
    )
    db.commit()
    return {"ok": True, "verification": out}


@router.post("/device/lease")
def lease_device(payload: dict[str, Any], claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    user_id = str(payload.get("user_id") or claims.get("sub") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()
    device_class = str(payload.get("device_class") or "desktop").strip().lower()

    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id_required")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id_required")
    if device_class not in {"desktop", "mobile"}:
        raise HTTPException(status_code=400, detail="device_class_invalid")

    try:
        out = service.lease_device(db=db, tenant_id=tenant_id, user_id=user_id, device_id=device_id, device_class=device_class)
    except ValueError as exc:
        detail = str(exc)
        status_code = 402 if detail in {"core_required", "core_seat_limit_exceeded"} else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="guard.device_lease",
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target=f"user/{user_id}",
        metadata={"device_id": device_id, "device_class": device_class, "replaced": out.get("replaced_previous")},
    )
    db.commit()
    return out


@router.get("/device/lease/me")
def get_my_lease(claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    user_id = str(claims.get("sub") or "").strip()
    if not tenant_id or not user_id:
        raise HTTPException(status_code=403, detail="missing_tenant_or_user_context")
    return service.get_lease(db=db, tenant_id=tenant_id, user_id=user_id)


@router.get("/tenant-status")
def tenant_status(claims: dict[str, Any] = Depends(require_claims), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    return service.tenant_status(db=db, tenant_id=tenant_id)


@router.get("/admin/bot/credentials")
def bot_credentials_list(
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "requested_by": claims.get("sub", "unknown"),
        "items": service.list_bot_credentials(db, tenant_id=tenant_id, limit=limit),
    }


@router.get("/admin/bot/lockouts")
def bot_lockouts(
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "requested_by": claims.get("sub", "unknown"),
        "items": service.list_locked_bot_credentials(db, tenant_id=tenant_id, limit=limit),
    }


@router.post("/admin/bot/credentials/issue")
def bot_credential_issue(
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    body = payload or {}
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.issue_bot_credential(db, tenant_id=tenant_id, actor=actor, label=str(body.get("label") or "").strip() or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_audit(
        db,
        action="guard.bot_credential_issued",
        actor=actor,
        tenant_id=tenant_id,
        target=f"guard/bot/{out.get('bot_id')}",
        metadata={"bot_id": out.get("bot_id"), "key_version": out.get("key_version")},
    )
    db.commit()
    return out


@router.post("/admin/bot/credentials/{bot_id}/rotate")
def bot_credential_rotate(
    bot_id: str,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.rotate_bot_credential(db, tenant_id=tenant_id, bot_id=bot_id, actor=actor)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "bot_credential_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="guard.bot_credential_rotated",
        actor=actor,
        tenant_id=tenant_id,
        target=f"guard/bot/{bot_id}",
        metadata={"key_version": out.get("key_version")},
    )
    db.commit()
    return out


@router.post("/admin/bot/credentials/{bot_id}/revoke")
def bot_credential_revoke(
    bot_id: str,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.revoke_bot_credential(db, tenant_id=tenant_id, bot_id=bot_id, actor=actor)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "bot_credential_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="guard.bot_credential_revoked",
        actor=actor,
        tenant_id=tenant_id,
        target=f"guard/bot/{bot_id}",
        metadata={"status": out.get("status")},
    )
    db.commit()
    return out


@router.post("/admin/bot/credentials/{bot_id}/unlock")
def bot_credential_unlock(
    bot_id: str,
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_tenant_admin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    body = payload or {}
    tenant_id = str(claims.get("tenant_id") or "").strip()
    actor = str(claims.get("sub") or "unknown")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    try:
        out = service.unlock_bot_credential(
            db,
            tenant_id=tenant_id,
            bot_id=bot_id,
            actor=actor,
            note=str(body.get("note") or "").strip() or None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if detail == "bot_credential_not_found" else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    write_audit(
        db,
        action="guard.bot_credential_unlocked_admin",
        actor=actor,
        tenant_id=tenant_id,
        target=f"guard/bot/{bot_id}",
        metadata={"status": out.get("status")},
    )
    db.commit()
    return out


@router.post("/admin/bot/check-once")
def admin_bot_check_once(
    payload: dict[str, Any] | None = None,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    body = payload or {}
    tenant_id = str(body.get("tenant_id") or "").strip() or None
    mode = str(body.get("mode") or "SCHEDULED").strip().upper()
    limit = int(body.get("limit") or 200)

    out = service.bot_sweep_once(
        db,
        actor=str(claims.get("sub") or "unknown"),
        tenant_id=tenant_id,
        limit=limit,
        mode=mode,
    )
    write_audit(
        db,
        action="guard.bot_check_once",
        actor=claims.get("sub", "unknown"),
        tenant_id=tenant_id,
        target="guard/bot/check-once",
        metadata={
            "run_id": out.get("run_id"),
            "checked_tenants": out.get("checked_tenants"),
            "restrict_tenants": out.get("restrict_tenants"),
            "mode": mode,
        },
    )
    db.commit()
    return out


@router.get("/admin/bot/checks")
def admin_bot_checks(
    tenant_id: str | None = None,
    limit: int = 200,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tid = tenant_id.strip() if tenant_id else None
    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "tenant_id": tid,
        "items": service.list_bot_checks(db, tenant_id=tid, limit=limit),
    }


@router.get("/admin/tenant-verify")
def admin_tenant_verify(
    tenant_id: str,
    stale_seconds: int | None = None,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    tid = str(tenant_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    out = service.verify_leases_vs_heartbeats(db=db, tenant_id=tid, stale_seconds=stale_seconds)
    write_audit(
        db,
        action="guard.admin_tenant_verify",
        actor=claims.get("sub", "unknown"),
        tenant_id=tid,
        target="guard/tenant-verify",
        metadata={
            "state": out.get("state"),
            "summary": out.get("summary"),
            "stale_seconds": out.get("stale_seconds"),
            "stale_enforced": out.get("stale_enforced"),
        },
    )
    db.commit()
    return {"ok": True, "requested_by": claims.get("sub", "unknown"), "verification": out}


@router.get("/admin/audit")
def admin_audit(limit: int = 200, claims: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db_session)) -> dict[str, Any]:
    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "items": list_audit(db=db, limit=limit),
    }


@router.get("/admin/audit/verify")
def admin_audit_verify(
    tenant_id: str | None = None,
    limit: int = 500,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 5000))
    out = verify_audit_chain(db=db, tenant_id=(tenant_id.strip() if tenant_id else None), limit=safe_limit)
    return {
        "ok": True,
        "requested_by": claims.get("sub", "unknown"),
        "verification": out,
    }