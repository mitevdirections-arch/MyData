from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Incident, StorageObjectMeta

ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_CATEGORIES = {"APP", "API", "DB", "INTEGRATION", "PERFORMANCE", "SECURITY", "OTHER"}
ALLOWED_STATUSES = {"OPEN", "ACKNOWLEDGED", "RESOLVED", "CLOSED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_severity(val: str) -> str:
    out = (val or "MEDIUM").strip().upper()
    if out not in ALLOWED_SEVERITIES:
        raise ValueError("incident_severity_invalid")
    return out


def _normalize_category(val: str) -> str:
    out = (val or "OTHER").strip().upper()
    if out not in ALLOWED_CATEGORIES:
        raise ValueError("incident_category_invalid")
    return out


def _normalize_status(val: str) -> str:
    out = (val or "OPEN").strip().upper()
    if out not in ALLOWED_STATUSES:
        raise ValueError("incident_status_invalid")
    return out


def _validate_evidence_ids(db: Session, *, tenant_id: str, evidence_ids: list[str]) -> list[str]:
    out: list[str] = []
    for raw in evidence_ids:
        try:
            oid = str(UUID(str(raw)))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("incident_evidence_id_invalid") from exc

        row = (
            db.query(StorageObjectMeta)
            .filter(
                StorageObjectMeta.id == oid,
                StorageObjectMeta.tenant_id == tenant_id,
                StorageObjectMeta.status == "ACTIVE",
            )
            .first()
        )
        if row is None:
            raise ValueError("incident_evidence_not_found_or_inactive")
        out.append(oid)
    return out


def _maybe_enqueue_security_alert(db: Session, *, row: Incident, actor: str) -> None:
    # Best-effort queue for security alert pipeline; incident creation must not fail if queue fails.
    try:
        from app.modules.security_ops.service import service as security_service

        security_service.auto_enqueue_for_incident(db, incident=row, actor=actor)
    except Exception:
        return


def create_incident(
    db: Session,
    *,
    tenant_id: str,
    created_by: str,
    title: str,
    description: str,
    severity: str,
    category: str,
    source: str,
    evidence_object_ids: list[str] | None,
) -> Incident:
    title_norm = (title or "").strip()
    if len(title_norm) < 5:
        raise ValueError("incident_title_too_short")
    if len(title_norm) > 180:
        raise ValueError("incident_title_too_long")

    description_norm = (description or "").strip()
    if len(description_norm) < 10:
        raise ValueError("incident_description_too_short")
    if len(description_norm) > 5000:
        raise ValueError("incident_description_too_long")

    evidence_ids = _validate_evidence_ids(db, tenant_id=tenant_id, evidence_ids=(evidence_object_ids or []))

    now = _now()
    row = Incident(
        tenant_id=tenant_id,
        status="OPEN",
        severity=_normalize_severity(severity),
        category=_normalize_category(category),
        source=(source or "TENANT").strip().upper(),
        title=title_norm,
        description=description_norm,
        evidence_object_ids=evidence_ids,
        created_by=created_by,
        acknowledged_by=None,
        acknowledged_at=None,
        resolved_by=None,
        resolved_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()

    _maybe_enqueue_security_alert(db, row=row, actor=created_by)

    db.commit()
    db.refresh(row)
    return row


def list_incidents_for_tenant(db: Session, *, tenant_id: str, status: str | None, limit: int = 100) -> list[Incident]:
    q = db.query(Incident).filter(Incident.tenant_id == tenant_id)
    if status:
        q = q.filter(Incident.status == _normalize_status(status))
    return q.order_by(Incident.created_at.desc()).limit(max(1, min(limit, 500))).all()


def list_incidents_global(db: Session, *, status: str | None, tenant_id: str | None, limit: int = 200) -> list[Incident]:
    q = db.query(Incident)
    if tenant_id:
        q = q.filter(Incident.tenant_id == tenant_id)
    if status:
        q = q.filter(Incident.status == _normalize_status(status))
    return q.order_by(Incident.created_at.desc()).limit(max(1, min(limit, 1000))).all()


def get_incident_for_tenant(db: Session, *, tenant_id: str, incident_id: str) -> Incident | None:
    return (
        db.query(Incident)
        .filter(Incident.id == incident_id, Incident.tenant_id == tenant_id)
        .first()
    )


def get_incident_global(db: Session, *, incident_id: str) -> Incident | None:
    return db.query(Incident).filter(Incident.id == incident_id).first()


def acknowledge_incident(db: Session, *, incident_id: str, actor: str) -> Incident:
    row = get_incident_global(db, incident_id=incident_id)
    if row is None:
        raise ValueError("incident_not_found")
    if row.status in {"RESOLVED", "CLOSED"}:
        raise ValueError("incident_already_resolved")

    row.status = "ACKNOWLEDGED"
    row.acknowledged_by = actor
    row.acknowledged_at = _now()
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def resolve_incident(db: Session, *, incident_id: str, actor: str, resolution_note: str | None) -> Incident:
    row = get_incident_global(db, incident_id=incident_id)
    if row is None:
        raise ValueError("incident_not_found")

    note = (resolution_note or "").strip()
    if note and len(note) > 4000:
        raise ValueError("incident_resolution_note_too_long")

    row.status = "RESOLVED"
    row.resolved_by = actor
    row.resolved_at = _now()
    row.resolution_note = note or None
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def to_dict(row: Incident) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "status": row.status,
        "severity": row.severity,
        "category": row.category,
        "source": row.source,
        "title": row.title,
        "description": row.description,
        "evidence_object_ids": row.evidence_object_ids or [],
        "created_by": row.created_by,
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolution_note": row.resolution_note,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }