from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog

CHAIN_VERSION = "v1"
_CHAIN_KEYS = {"chain_version", "prev_hash", "audit_hash"}


def _clean_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(metadata or {})
    for k in _CHAIN_KEYS:
        base.pop(k, None)
    return base


def _hash_for_row(*, ts_iso: str, action: str, actor: str, tenant_id: str | None, target: str | None, metadata_json: dict[str, Any], prev_hash: str) -> str:
    payload = {
        "chain_version": CHAIN_VERSION,
        "ts": ts_iso,
        "action": action,
        "actor": actor,
        "tenant_id": tenant_id,
        "target": target,
        "metadata": metadata_json,
        "prev_hash": prev_hash,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_hash_for_stream(db: Session, *, tenant_id: str | None) -> str:
    q = db.query(AuditLog)
    if tenant_id is None:
        q = q.filter(AuditLog.tenant_id.is_(None))
    else:
        q = q.filter(AuditLog.tenant_id == tenant_id)

    last = q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).first()
    if not last or not isinstance(last.metadata_json, dict):
        return "GENESIS"
    h = str(last.metadata_json.get("audit_hash") or "").strip().lower()
    return h or "GENESIS"


def write_audit(
    db: Session,
    *,
    action: str,
    actor: str,
    tenant_id: str | None,
    target: str | None,
    metadata: dict | None = None,
) -> None:
    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat()
    clean_meta = _clean_metadata(metadata)
    prev_hash = _latest_hash_for_stream(db, tenant_id=tenant_id)
    audit_hash = _hash_for_row(
        ts_iso=ts_iso,
        action=action,
        actor=actor,
        tenant_id=tenant_id,
        target=target,
        metadata_json=clean_meta,
        prev_hash=prev_hash,
    )

    final_meta = {
        **clean_meta,
        "chain_version": CHAIN_VERSION,
        "prev_hash": prev_hash,
        "audit_hash": audit_hash,
    }

    db.add(
        AuditLog(
            ts=ts,
            action=action,
            actor=actor,
            tenant_id=tenant_id,
            target=target,
            metadata_json=final_meta,
        )
    )


def list_audit(db: Session, limit: int = 200) -> list[dict]:
    q = db.query(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(max(1, min(limit, 2000)))
    rows = q.all()
    return [
        {
            "ts": r.ts.isoformat(),
            "action": r.action,
            "actor": r.actor,
            "tenant_id": r.tenant_id,
            "target": r.target,
            "metadata": r.metadata_json,
        }
        for r in rows
    ]


def _verify_stream(rows: list[AuditLog]) -> tuple[int, int, int, str | None]:
    checked = 0
    legacy_without_chain = 0
    broken = 0
    expected_prev = "GENESIS"

    for row in rows:
        m = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        prev_hash = str(m.get("prev_hash") or "").strip()
        audit_hash = str(m.get("audit_hash") or "").strip().lower()
        chain_version = str(m.get("chain_version") or "").strip()

        if not audit_hash or not chain_version:
            legacy_without_chain += 1
            continue

        clean_meta = _clean_metadata(m)
        recomputed = _hash_for_row(
            ts_iso=row.ts.isoformat(),
            action=row.action,
            actor=row.actor,
            tenant_id=row.tenant_id,
            target=row.target,
            metadata_json=clean_meta,
            prev_hash=prev_hash,
        )

        ok_link = (prev_hash == expected_prev)
        ok_hash = (recomputed == audit_hash)
        if not (ok_link and ok_hash):
            broken += 1
        else:
            expected_prev = audit_hash

        checked += 1

    return checked, legacy_without_chain, broken, (expected_prev if checked > 0 else None)


def verify_audit_chain(db: Session, *, tenant_id: str | None = None, limit: int = 5000) -> dict[str, Any]:
    q = db.query(AuditLog)
    if tenant_id is not None:
        q = q.filter(AuditLog.tenant_id == tenant_id)
    rows = q.order_by(AuditLog.ts.asc(), AuditLog.id.asc()).limit(max(1, min(limit, 20000))).all()

    if tenant_id is not None:
        checked, legacy, broken, head = _verify_stream(rows)
        return {
            "ok": broken == 0,
            "tenant_id": tenant_id,
            "chain_version": CHAIN_VERSION,
            "checked": checked,
            "legacy_without_chain": legacy,
            "broken": broken,
            "head_hash": head,
        }

    # Global verification is stream-aware (per tenant_id) because hash chains are per stream.
    by_stream: dict[str | None, list[AuditLog]] = {}
    for r in rows:
        by_stream.setdefault(r.tenant_id, []).append(r)

    total_checked = 0
    total_legacy = 0
    total_broken = 0
    stream_heads: dict[str, str | None] = {}

    for stream_tenant, stream_rows in by_stream.items():
        c, l, b, h = _verify_stream(stream_rows)
        total_checked += c
        total_legacy += l
        total_broken += b
        stream_heads[str(stream_tenant) if stream_tenant is not None else "__platform__"] = h

    return {
        "ok": total_broken == 0,
        "tenant_id": None,
        "chain_version": CHAIN_VERSION,
        "checked": total_checked,
        "legacy_without_chain": total_legacy,
        "broken": total_broken,
        "head_hash": None,
        "stream_heads": stream_heads,
        "streams": len(by_stream),
    }
