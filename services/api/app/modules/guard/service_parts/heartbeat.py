from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import DeviceLease, GuardBehaviorState, GuardHeartbeat


class GuardHeartbeatMixin:
    def get_behavior_policy(self, db: Session, *, tenant_id: str) -> dict:
        row = self._get_or_create_behavior(db, tenant_id)
        return {
            "tenant_id": tenant_id,
            "good_since": row.good_since.isoformat(),
            "suspicion_count": int(row.suspicion_count),
            "last_suspicion_at": row.last_suspicion_at.isoformat() if row.last_suspicion_at else None,
            "current_multiplier": int(row.current_multiplier),
            "recommended_interval_seconds": int(row.recommended_interval_seconds),
            "next_heartbeat_due_at": row.next_heartbeat_due_at.isoformat() if row.next_heartbeat_due_at else None,
            "session_open": bool(row.session_open),
            "last_event": row.last_event,
            "last_device_id": row.last_device_id,
            "last_status": row.last_status,
            "last_flags": row.last_flags_json or {},
            "updated_at": row.updated_at.isoformat(),
        }

    def ingest(
        self,
        db: Session,
        *,
        tenant_id: str,
        device_id: str,
        user_id: str | None,
        status: str = "OK",
        event: str = "KEEPALIVE",
        flags: dict | None = None,
    ) -> dict:
        now = self._now()
        event_val = self._normalize_event(event)
        flags_val = self._normalize_flags(flags)
        status_val = str(status or "OK").strip().upper()

        hb = (
            db.query(GuardHeartbeat)
            .filter(GuardHeartbeat.tenant_id == tenant_id, GuardHeartbeat.device_id == device_id)
            .first()
        )
        if hb is None:
            hb = GuardHeartbeat(
                tenant_id=tenant_id,
                device_id=device_id,
                status=status_val,
                last_heartbeat_at=now,
            )
            db.add(hb)
        else:
            hb.status = status_val
            hb.last_heartbeat_at = now

        # Keep lease activity fresh when heartbeat is from an active leased device.
        lease = (
            db.query(DeviceLease)
            .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.device_id == device_id, DeviceLease.is_active == True)  # noqa: E712
            .first()
        )
        if lease is not None:
            lease.last_seen_at = now

        behavior = self._get_or_create_behavior(db, tenant_id)

        suspicious = bool(flags_val.get("suspected_abuse")) or status_val != "OK"
        if suspicious:
            behavior.good_since = now
            behavior.suspicion_count = int(behavior.suspicion_count) + 1
            behavior.last_suspicion_at = now

        multiplier = self._calc_multiplier(behavior.good_since, suspicious)
        base_seconds = max(60, int(get_settings().guard_heartbeat_base_seconds))
        interval_seconds = int(base_seconds * max(1, multiplier))
        interval_seconds, expiry_priority = self._apply_license_expiry_priority(db, tenant_id, interval_seconds)

        session_end = event_val == "LOGOUT" or bool(flags_val.get("session_end"))
        if session_end:
            behavior.session_open = False
            behavior.next_heartbeat_due_at = None
        else:
            behavior.session_open = True
            behavior.next_heartbeat_due_at = now + timedelta(seconds=interval_seconds)

        behavior.current_multiplier = int(multiplier)
        behavior.recommended_interval_seconds = int(interval_seconds)
        behavior.last_event = event_val
        behavior.last_device_id = device_id
        behavior.last_status = status_val
        behavior.last_flags_json = flags_val
        behavior.updated_at = now

        db.commit()

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device_id": device_id,
            "status": status_val,
            "event": event_val,
            "flags": flags_val,
            "at": now.isoformat(),
            "lease_linked": lease is not None,
            "heartbeat_policy": {
                "good_since": behavior.good_since.isoformat(),
                "suspicion_count": int(behavior.suspicion_count),
                "last_suspicion_at": behavior.last_suspicion_at.isoformat() if behavior.last_suspicion_at else None,
                "multiplier": int(multiplier),
                "base_interval_seconds": int(base_seconds),
                "recommended_interval_seconds": int(interval_seconds),
                "next_heartbeat_due_at": behavior.next_heartbeat_due_at.isoformat() if behavior.next_heartbeat_due_at else None,
                "session_open": bool(behavior.session_open),
                "expiry_priority": expiry_priority,
            },
        }

    def verify_leases_vs_heartbeats(self, db: Session, *, tenant_id: str, stale_seconds: int | None = None) -> dict:
        now = self._now()
        s = get_settings()

        behavior = db.query(GuardBehaviorState).filter(GuardBehaviorState.tenant_id == tenant_id).first()
        fallback_sec = int(stale_seconds) if stale_seconds is not None else int(s.guard_heartbeat_stale_seconds)
        fallback_sec = max(30, min(fallback_sec, 86400))

        policy_interval = int(behavior.recommended_interval_seconds) if behavior is not None else fallback_sec
        policy_interval = max(30, policy_interval)
        stale_sec = max(fallback_sec, policy_interval + 300)
        stale_cutoff = now - timedelta(seconds=stale_sec)
        stale_enforced = bool(behavior.session_open) if behavior is not None else True

        leases = (
            db.query(DeviceLease)
            .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.is_active == True)  # noqa: E712
            .order_by(DeviceLease.leased_at.asc())
            .all()
        )
        heartbeats = db.query(GuardHeartbeat).filter(GuardHeartbeat.tenant_id == tenant_id).all()

        hb_by_device: dict[str, GuardHeartbeat] = {}
        for hb in heartbeats:
            curr = hb_by_device.get(hb.device_id)
            if curr is None or hb.last_heartbeat_at > curr.last_heartbeat_at:
                hb_by_device[hb.device_id] = hb

        missing = 0
        stale = 0
        bad_status = 0
        checks: list[dict] = []

        for lease in leases:
            hb = hb_by_device.get(lease.device_id)
            if hb is None:
                if stale_enforced:
                    missing += 1
                    result = "MISSING_HEARTBEAT"
                else:
                    result = "NO_HEARTBEAT_SESSION_CLOSED"
                checks.append(
                    {
                        "user_id": lease.user_id,
                        "device_id": lease.device_id,
                        "device_class": lease.device_class,
                        "result": result,
                        "last_heartbeat_at": None,
                    }
                )
                continue

            hb_status = str(hb.status or "UNKNOWN").upper()
            is_stale = stale_enforced and hb.last_heartbeat_at < stale_cutoff
            is_bad = hb_status != "OK"

            if is_bad:
                bad_status += 1
                result = "BAD_STATUS"
            elif is_stale:
                stale += 1
                result = "STALE_HEARTBEAT"
            else:
                result = "OK"

            checks.append(
                {
                    "user_id": lease.user_id,
                    "device_id": lease.device_id,
                    "device_class": lease.device_class,
                    "result": result,
                    "heartbeat_status": hb_status,
                    "last_heartbeat_at": hb.last_heartbeat_at.isoformat(),
                }
            )

        leased_device_ids = {x.device_id for x in leases}
        orphan_heartbeats = [
            {
                "device_id": hb.device_id,
                "status": hb.status,
                "last_heartbeat_at": hb.last_heartbeat_at.isoformat(),
            }
            for hb in heartbeats
            if hb.device_id not in leased_device_ids
        ]

        state = "RESTRICT" if (missing > 0 or stale > 0 or bad_status > 0) else "ALLOW"

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "state": state,
            "stale_seconds": int(stale_sec),
            "stale_enforced": bool(stale_enforced),
            "summary": {
                "active_leases": len(leases),
                "heartbeats": len(heartbeats),
                "missing_heartbeat": missing,
                "stale_heartbeat": stale,
                "bad_status": bad_status,
                "orphan_heartbeats": len(orphan_heartbeats),
            },
            "heartbeat_policy": self.get_behavior_policy(db, tenant_id=tenant_id),
            "checks": checks,
            "orphan_heartbeats": orphan_heartbeats,
        }

