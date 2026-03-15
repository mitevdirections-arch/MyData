from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import urllib.request
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.core.startup_security import collect_startup_security_issues, is_prod_env
from app.db.models import AuditLog, GuardBotCredential, Incident, License, SecurityAlertQueue, Tenant

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
QUEUE_STATUSES_OPEN = {"PENDING", "RETRY_SCHEDULED"}
QUEUE_STATUSES_ALL = {"PENDING", "RETRY_SCHEDULED", "DELIVERED", "FAILED"}


class SecurityOpsService:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _fingerprint(self, secret: str | None) -> str:
        raw = str(secret or "").encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _secret_profile(self, *, name: str, value: str | None, rotated_at: str | None, max_age_days: int) -> dict[str, Any]:
        raw = str(value or "")
        rot = str(rotated_at or "").strip()

        dt = None
        age_days = None
        stale = None
        if rot:
            try:
                dt = datetime.fromisoformat(rot.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
                age_days = (self._now() - dt).days
                stale = bool(age_days > max_age_days)
            except ValueError:
                dt = None

        return {
            "name": name,
            "fingerprint": self._fingerprint(raw),
            "length": len(raw),
            "default_like": str(raw).strip().lower().startswith("change-me") or not str(raw).strip(),
            "rotated_at": dt.isoformat() if dt else (rot or None),
            "age_days": age_days,
            "max_age_days": int(max_age_days),
            "stale": stale,
        }

    def posture(self) -> dict[str, Any]:
        s = get_settings()
        prod = is_prod_env(s.app_env)
        issues = collect_startup_security_issues(s)

        profiles = [
            self._secret_profile(
                name="JWT_SECRET",
                value=s.jwt_secret,
                rotated_at=s.jwt_secret_rotated_at,
                max_age_days=s.secret_rotation_max_age_days,
            ),
            self._secret_profile(
                name="STORAGE_GRANT_SECRET",
                value=s.storage_grant_secret,
                rotated_at=s.storage_grant_secret_rotated_at,
                max_age_days=s.secret_rotation_max_age_days,
            ),
            self._secret_profile(
                name="GUARD_BOT_SIGNING_MASTER_SECRET",
                value=s.guard_bot_signing_master_secret,
                rotated_at=s.guard_bot_signing_master_secret_rotated_at,
                max_age_days=s.secret_rotation_max_age_days,
            ),
        ]

        checks = [
            {
                "id": "startup_guardrails",
                "ok": len(issues) == 0,
                "details": issues,
            },
            {
                "id": "dev_token_route",
                "ok": (not prod) or (not bool(s.auth_dev_token_enabled)),
                "details": {
                    "app_env": s.app_env,
                    "auth_dev_token_enabled": bool(s.auth_dev_token_enabled),
                },
            },
            {
                "id": "guard_bot_signature",
                "ok": (not prod) or bool(s.guard_bot_signature_required),
                "details": {
                    "guard_bot_signature_required": bool(s.guard_bot_signature_required),
                },
            },
            {
                "id": "cors_policy",
                "ok": (not prod) or ("*" not in s.cors_origins_list() and bool(s.cors_origins_list())),
                "details": {
                    "origins": s.cors_origins_list(),
                },
            },
        ]

        total = len(checks)
        passed = sum(1 for c in checks if bool(c.get("ok")))
        score = int((passed * 100) / total) if total else 0

        return {
            "ok": len(issues) == 0,
            "app_env": s.app_env,
            "prod_mode": prod,
            "score": score,
            "checks": checks,
            "issues": issues,
            "secret_profiles": profiles,
            "alerting": {
                "enabled": bool(s.security_alerts_enabled),
                "delivery_mode": str(s.security_alerts_delivery_mode or "LOG_ONLY").upper(),
                "webhook_configured": bool(str(s.security_alert_webhook_url or "").strip()),
                "min_severity": str(s.security_alert_min_severity or "HIGH").upper(),
            },
        }

    def key_lifecycle(self) -> dict[str, Any]:
        s = get_settings()
        posture = self.posture()
        profiles = {str(x.get("name") or ""): x for x in list(posture.get("secret_profiles") or [])}

        out = {
            "ok": True,
            "versions": {
                "JWT_SECRET_VERSION": int(s.jwt_secret_version),
                "STORAGE_GRANT_SECRET_VERSION": int(s.storage_grant_secret_version),
                "GUARD_BOT_SIGNING_MASTER_SECRET_VERSION": int(s.guard_bot_signing_master_secret_version),
            },
            "rotation": {
                "JWT_SECRET": profiles.get("JWT_SECRET") or {},
                "STORAGE_GRANT_SECRET": profiles.get("STORAGE_GRANT_SECRET") or {},
                "GUARD_BOT_SIGNING_MASTER_SECRET": profiles.get("GUARD_BOT_SIGNING_MASTER_SECRET") or {},
            },
            "policy": {
                "max_age_days": int(s.secret_rotation_max_age_days),
                "step_up_enabled": bool(s.superadmin_step_up_enabled),
                "step_up_header": str(s.superadmin_step_up_header or "X-Step-Up-Code"),
            },
            "recommended_actions": [],
        }

        for name, prof in list(out["rotation"].items()):
            if bool((prof or {}).get("default_like")):
                out["recommended_actions"].append(f"rotate_now:{name}:default_like")
            if bool((prof or {}).get("stale")):
                out["recommended_actions"].append(f"rotate_now:{name}:stale")

        if not bool(s.superadmin_step_up_enabled):
            out["recommended_actions"].append("enable_step_up_mfa")

        return out

    def emergency_lock_tenant(self, db: Session, *, tenant_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
        tid = str(tenant_id or "").strip()
        if not tid:
            raise ValueError("tenant_id_required")

        tenant = db.query(Tenant).filter(Tenant.id == tid).first()
        if tenant is None:
            raise ValueError("tenant_not_found")

        now = self._now()
        actor_id = str(actor or "unknown")
        lock_reason = str(reason or "kill_switch").strip()[:2000]

        tenant_was_active = bool(tenant.is_active)
        tenant.is_active = False

        lic_rows = db.query(License).filter(License.tenant_id == tid, License.status == "ACTIVE").all()
        for row in lic_rows:
            row.status = "SUSPENDED"

        bot_rows = db.query(GuardBotCredential).filter(GuardBotCredential.tenant_id == tid, GuardBotCredential.status == "ACTIVE").all()
        for row in bot_rows:
            row.status = "REVOKED"
            row.revoked_by = actor_id
            row.revoked_at = now

        incident = Incident(
            tenant_id=tid,
            status="OPEN",
            severity="CRITICAL",
            category="SECURITY",
            source="KILL_SWITCH",
            title="Emergency tenant lock activated",
            description=f"Tenant lock by {actor_id}. Reason: {lock_reason}",
            resolution_note=None,
            evidence_object_ids=[],
            created_by=actor_id,
            acknowledged_by=None,
            acknowledged_at=None,
            resolved_by=None,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(incident)
        db.flush()

        queued = self.auto_enqueue_for_incident(db, incident=incident, actor=actor_id)
        db.flush()

        return {
            "ok": True,
            "tenant_id": tid,
            "tenant_was_active": tenant_was_active,
            "tenant_is_active": bool(tenant.is_active),
            "suspended_licenses": len(lic_rows),
            "revoked_bot_credentials": len(bot_rows),
            "incident_id": str(incident.id),
            "queued_alert": queued,
            "reason": lock_reason,
            "locked_at": now.isoformat(),
            "locked_by": actor_id,
        }

    def _event_to_dict(self, row: AuditLog) -> dict[str, Any]:
        meta = dict(row.metadata_json or {})
        severity = str(meta.get("severity") or "MEDIUM").strip().upper()
        if severity not in SEVERITY_RANK:
            severity = "MEDIUM"

        return {
            "id": str(row.id),
            "ts": row.ts.isoformat() if row.ts else None,
            "action": row.action,
            "event_code": row.action.removeprefix("security.event."),
            "severity": severity,
            "category": str(meta.get("category") or "SECURITY").strip().upper(),
            "source": str(meta.get("source") or "API").strip().upper(),
            "actor": row.actor,
            "tenant_id": row.tenant_id,
            "target": row.target,
            "request_id": str(meta.get("request_id") or "") or None,
            "request_path": str(meta.get("request_path") or "") or None,
            "request_method": str(meta.get("request_method") or "") or None,
            "ip": str(meta.get("ip") or "") or None,
            "details": dict(meta.get("details") or {}),
        }

    def list_security_events(self, db: Session, *, tenant_id: str | None, severity: str | None, limit: int = 200) -> list[dict[str, Any]]:
        sev = str(severity or "").strip().upper()
        if sev and sev not in SEVERITY_RANK:
            raise ValueError("security_event_severity_invalid")

        lim = max(1, min(int(limit), 2000))
        scan_limit = max(lim * 8, 500)

        q = db.query(AuditLog).filter(AuditLog.action.like("security.event.%"))
        if tenant_id:
            q = q.filter(AuditLog.tenant_id == str(tenant_id).strip())

        rows = q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(scan_limit).all()

        out: list[dict[str, Any]] = []
        for row in rows:
            item = self._event_to_dict(row)
            if sev and str(item.get("severity") or "") != sev:
                continue
            out.append(item)
            if len(out) >= lim:
                break

        return out
    def _severity_allowed(self, severity: str) -> bool:
        s = get_settings()
        min_sev = str(s.security_alert_min_severity or "HIGH").strip().upper()
        min_rank = SEVERITY_RANK.get(min_sev, 3)
        rank = SEVERITY_RANK.get(str(severity or "MEDIUM").strip().upper(), 2)
        return rank >= min_rank

    def _queue_to_dict(self, row: SecurityAlertQueue) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "incident_id": str(row.incident_id),
            "tenant_id": row.tenant_id,
            "channel": row.channel,
            "status": row.status,
            "attempts": int(row.attempts),
            "max_attempts": int(row.max_attempts),
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "last_error": row.last_error,
            "payload": row.payload_json or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        }

    def auto_enqueue_for_incident(self, db: Session, *, incident: Incident, actor: str) -> dict[str, Any] | None:
        s = get_settings()
        if not bool(s.security_alerts_enabled):
            return None

        if not self._severity_allowed(str(incident.severity or "MEDIUM")) and str(incident.category or "").upper() != "SECURITY":
            return None

        existing = (
            db.query(SecurityAlertQueue)
            .filter(SecurityAlertQueue.incident_id == incident.id, SecurityAlertQueue.status.in_(list(QUEUE_STATUSES_OPEN | {"DELIVERED"})))
            .first()
        )
        if existing is not None:
            return self._queue_to_dict(existing)

        mode = str(s.security_alerts_delivery_mode or "LOG_ONLY").strip().upper()
        channel = "WEBHOOK" if mode == "WEBHOOK" else "LOG"

        now = self._now()
        row = SecurityAlertQueue(
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            channel=channel,
            status="PENDING",
            payload_json={
                "incident": {
                    "id": str(incident.id),
                    "tenant_id": incident.tenant_id,
                    "severity": incident.severity,
                    "category": incident.category,
                    "source": incident.source,
                    "title": incident.title,
                    "description": incident.description,
                    "created_at": incident.created_at.isoformat() if incident.created_at else None,
                },
                "queued_by": str(actor or "unknown"),
            },
            attempts=0,
            max_attempts=max(1, int(s.security_alert_retry_max_attempts)),
            next_attempt_at=now,
            last_error=None,
            created_at=now,
            updated_at=now,
            processed_at=None,
        )
        db.add(row)
        db.flush()
        return self._queue_to_dict(row)

    def create_test_incident_and_queue(self, db: Session, *, tenant_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "Security pipeline test alert").strip()[:180]
        description = str(payload.get("description") or "Test alert from security_ops module").strip()[:5000]
        severity = str(payload.get("severity") or "HIGH").strip().upper()
        if severity not in SEVERITY_RANK:
            severity = "HIGH"

        now = self._now()
        incident = Incident(
            tenant_id=tenant_id,
            status="OPEN",
            severity=severity,
            category="SECURITY",
            source="SECURITY_GATE",
            title=title,
            description=description,
            resolution_note=None,
            evidence_object_ids=[],
            created_by=str(actor or "unknown"),
            acknowledged_by=None,
            acknowledged_at=None,
            resolved_by=None,
            resolved_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(incident)
        db.flush()

        queued = self.auto_enqueue_for_incident(db, incident=incident, actor=actor)
        return {
            "incident": {
                "id": str(incident.id),
                "tenant_id": incident.tenant_id,
                "status": incident.status,
                "severity": incident.severity,
                "category": incident.category,
                "source": incident.source,
                "title": incident.title,
            },
            "queued_alert": queued,
        }

    def list_alert_queue(self, db: Session, *, status: str | None, tenant_id: str | None, limit: int = 200) -> list[dict[str, Any]]:
        q = db.query(SecurityAlertQueue)
        if status:
            st = str(status or "").strip().upper()
            if st not in QUEUE_STATUSES_ALL:
                raise ValueError("security_alert_status_invalid")
            q = q.filter(SecurityAlertQueue.status == st)
        if tenant_id:
            q = q.filter(SecurityAlertQueue.tenant_id == str(tenant_id).strip())

        rows = q.order_by(SecurityAlertQueue.created_at.desc()).limit(max(1, min(int(limit), 2000))).all()
        return [self._queue_to_dict(x) for x in rows]

    def _deliver_alert(self, row: SecurityAlertQueue) -> tuple[bool, str | None]:
        s = get_settings()
        mode = str(s.security_alerts_delivery_mode or "LOG_ONLY").strip().upper()

        if mode != "WEBHOOK":
            return True, None

        webhook = str(s.security_alert_webhook_url or "").strip()
        if not webhook:
            return False, "webhook_url_not_configured"

        body = json.dumps(row.payload_json or {}, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1, int(s.security_alert_dispatch_batch_size // 50 or 5))) as resp:  # noqa: S310
                if int(getattr(resp, "status", 500)) >= 400:
                    return False, f"http_{int(resp.status)}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

        return True, None

    def dispatch_once(self, db: Session, *, actor: str, limit: int = 200) -> dict[str, Any]:
        s = get_settings()
        now = self._now()

        rows = (
            db.query(SecurityAlertQueue)
            .filter(SecurityAlertQueue.status.in_(list(QUEUE_STATUSES_OPEN)), SecurityAlertQueue.next_attempt_at <= now)
            .order_by(SecurityAlertQueue.next_attempt_at.asc(), SecurityAlertQueue.created_at.asc())
            .limit(max(1, min(int(limit), max(1, int(s.security_alert_dispatch_batch_size)))))
            .all()
        )

        processed = 0
        delivered = 0
        failed = 0
        retried = 0

        for row in rows:
            processed += 1
            ok, err = self._deliver_alert(row)
            row.attempts = int(row.attempts) + 1
            row.updated_at = self._now()

            if ok:
                row.status = "DELIVERED"
                row.processed_at = self._now()
                row.last_error = None
                delivered += 1
                continue

            row.last_error = str(err or "alert_delivery_failed")[:2000]
            if int(row.attempts) >= int(row.max_attempts):
                row.status = "FAILED"
                row.processed_at = self._now()
                failed += 1
            else:
                row.status = "RETRY_SCHEDULED"
                base = max(1, int(s.security_alert_retry_base_seconds))
                cap = max(base, int(s.security_alert_retry_max_seconds))
                backoff = min(base * (2 ** max(0, int(row.attempts) - 1)), cap)
                row.next_attempt_at = self._now() + timedelta(seconds=backoff)
                retried += 1

        db.flush()
        return {
            "processed": processed,
            "delivered": delivered,
            "failed": failed,
            "retried": retried,
            "requested_by": str(actor or "unknown"),
        }

    def _get_alert(self, db: Session, alert_id: str) -> SecurityAlertQueue:
        try:
            aid = UUID(str(alert_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("security_alert_id_invalid") from exc
        row = db.query(SecurityAlertQueue).filter(SecurityAlertQueue.id == aid).first()
        if row is None:
            raise ValueError("security_alert_not_found")
        return row

    def requeue(self, db: Session, *, alert_id: str, actor: str) -> dict[str, Any]:
        row = self._get_alert(db, alert_id)
        row.status = "PENDING"
        row.next_attempt_at = self._now()
        row.last_error = None
        row.updated_at = self._now()
        row.processed_at = None
        payload = dict(row.payload_json or {})
        payload["requeued_by"] = str(actor or "unknown")
        row.payload_json = payload
        db.flush()
        return self._queue_to_dict(row)

    def fail_now(self, db: Session, *, alert_id: str, actor: str, reason: str | None) -> dict[str, Any]:
        row = self._get_alert(db, alert_id)
        row.status = "FAILED"
        row.processed_at = self._now()
        row.updated_at = self._now()
        row.last_error = str(reason or "failed_by_operator")[:2000]
        payload = dict(row.payload_json or {})
        payload["failed_by"] = str(actor or "unknown")
        row.payload_json = payload
        db.flush()
        return self._queue_to_dict(row)


service = SecurityOpsService()