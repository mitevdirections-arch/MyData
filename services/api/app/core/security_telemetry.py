from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.db.models import Incident

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_code(code: str) -> str:
    raw = "".join(ch if ch.isalnum() else "_" for ch in str(code or "").strip().upper())
    raw = raw.strip("_")
    return raw or "UNKNOWN"


def _clean_severity(severity: str | None) -> str:
    sev = str(severity or "MEDIUM").strip().upper()
    return sev if sev in SEVERITY_RANK else "MEDIUM"


def _short_json(data: dict[str, Any] | None, *, max_chars: int = 3000) -> str:
    body = str(data or {})
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "..."


def emit_security_event(
    db: Session,
    *,
    event_code: str,
    severity: str,
    actor: str,
    tenant_id: str | None,
    target: str | None,
    source: str,
    category: str = "SECURITY",
    request_id: str | None = None,
    request_path: str | None = None,
    request_method: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
    create_incident_for_high: bool = True,
) -> dict[str, Any]:
    code = _clean_code(event_code)
    sev = _clean_severity(severity)
    act = str(actor or "unknown")[:255]
    tid = str(tenant_id or "").strip() or None

    metadata = {
        "event_code": code,
        "severity": sev,
        "category": str(category or "SECURITY").strip().upper() or "SECURITY",
        "source": str(source or "API").strip().upper() or "API",
        "request_id": str(request_id or "").strip() or None,
        "request_path": str(request_path or "").strip() or None,
        "request_method": str(request_method or "").strip().upper() or None,
        "ip": str(ip or "").strip() or None,
        "details": dict(details or {}),
    }

    write_audit(
        db,
        action=f"security.event.{code.lower()}",
        actor=act,
        tenant_id=tid,
        target=str(target or "")[:255] or None,
        metadata=metadata,
    )

    incident_id: str | None = None
    alert_id: str | None = None
    if create_incident_for_high and tid and SEVERITY_RANK.get(sev, 0) >= SEVERITY_RANK["HIGH"]:
        now = _now()
        title = f"Security event: {code}"
        description = (
            f"Structured security event {code} recorded by {act}. "
            f"Details: {_short_json(metadata.get('details') or {})}"
        )
        row = Incident(
            tenant_id=tid,
            status="OPEN",
            severity=sev,
            category="SECURITY",
            source=str(source or "SECURITY_GATE").strip().upper() or "SECURITY_GATE",
            title=title[:180],
            description=description[:5000],
            resolution_note=None,
            evidence_object_ids=[],
            created_by=act,
            acknowledged_by=None,
            acknowledged_at=None,
            resolved_by=None,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        incident_id = str(row.id)

        try:
            from app.modules.security_ops.service import service as security_service

            queued = security_service.auto_enqueue_for_incident(db, incident=row, actor=act)
            alert_id = str((queued or {}).get("id") or "") or None
        except Exception:  # noqa: BLE001
            alert_id = None

    return {
        "event_code": code,
        "severity": sev,
        "tenant_id": tid,
        "incident_id": incident_id,
        "alert_id": alert_id,
    }