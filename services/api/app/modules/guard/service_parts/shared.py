from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import GuardBehaviorState
from app.modules.licensing.service import service as licensing_service

VALID_HEARTBEAT_EVENTS = {"STARTUP", "KEEPALIVE", "LOGOUT"}


class GuardSharedMixin:
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _normalize_event(self, event: str | None) -> str:
        val = str(event or "KEEPALIVE").strip().upper()
        if val not in VALID_HEARTBEAT_EVENTS:
            raise ValueError("heartbeat_event_invalid")
        return val

    def _normalize_flags(self, flags: dict | None) -> dict:
        raw = flags if isinstance(flags, dict) else {}
        return {
            "suspected_abuse": bool(raw.get("suspected_abuse", False)),
            "session_end": bool(raw.get("session_end", False)),
            "manual_review": bool(raw.get("manual_review", False)),
        }

    def _get_or_create_behavior(self, db: Session, tenant_id: str) -> GuardBehaviorState:
        row = db.query(GuardBehaviorState).filter(GuardBehaviorState.tenant_id == tenant_id).first()
        if row is None:
            now = self._now()
            s = get_settings()
            row = GuardBehaviorState(
                tenant_id=tenant_id,
                good_since=now,
                suspicion_count=0,
                current_multiplier=1,
                recommended_interval_seconds=max(60, int(s.guard_heartbeat_base_seconds)),
                next_heartbeat_due_at=None,
                session_open=False,
                last_event=None,
                last_device_id=None,
                last_status=None,
                last_flags_json={},
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
        return row

    def _calc_multiplier(self, good_since: datetime, suspicious_now: bool) -> int:
        s = get_settings()
        if suspicious_now:
            return 1

        week_days = max(1, int(s.guard_heartbeat_good_week_days))
        max_mul = max(1, int(s.guard_heartbeat_max_multiplier))
        days = max(0, (self._now() - good_since).days)
        return min(1 + (days // week_days), max_mul)

    def _apply_license_expiry_priority(self, db: Session, tenant_id: str, interval_seconds: int) -> tuple[int, dict]:
        s = get_settings()
        now = self._now()
        nearest = licensing_service.get_nearest_active_license_expiry(db, tenant_id)

        info = {
            "active_license_expires_at": nearest.isoformat() if nearest else None,
            "priority_applied": False,
            "reason": "none",
            "adjusted_interval_seconds": int(interval_seconds),
        }
        if nearest is None:
            return int(interval_seconds), info

        delta = (nearest - now).total_seconds()
        cap = None
        reason = "none"

        if delta <= 0:
            cap = int(s.guard_license_expiry_emergency_seconds)
            reason = "license_expired_or_due"
        elif delta <= int(s.guard_license_expiry_emergency_hours) * 3600:
            cap = int(s.guard_license_expiry_emergency_seconds)
            reason = "license_expiry_emergency_window"
        elif delta <= int(s.guard_license_expiry_critical_hours) * 3600:
            cap = int(s.guard_license_expiry_critical_seconds)
            reason = "license_expiry_critical_window"
        elif delta <= int(s.guard_license_expiry_window_hours) * 3600:
            cap = int(s.guard_license_expiry_tighten_seconds)
            reason = "license_expiry_window"

        if cap is None:
            return int(interval_seconds), info

        adjusted = min(int(interval_seconds), max(60, int(cap)))
        info["priority_applied"] = adjusted < int(interval_seconds)
        info["reason"] = reason
        info["adjusted_interval_seconds"] = adjusted
        return adjusted, info

