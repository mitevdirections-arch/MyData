from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import DeviceLease
from app.modules.licensing.service import service as licensing_service


class GuardSecurityLeaseMixin:
    def record_security_flag(
        self,
        db: Session,
        *,
        tenant_id: str,
        reason: str,
        module_code: str | None,
        actor: str,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        now = self._now()
        behavior = self._get_or_create_behavior(db, tenant_id)
        behavior.good_since = now
        behavior.suspicion_count = int(behavior.suspicion_count) + 1
        behavior.last_suspicion_at = now
        behavior.last_event = "SECURITY_FLAG"
        behavior.last_status = "ALERT"
        behavior.last_device_id = None
        behavior.last_flags_json = {
            **(behavior.last_flags_json or {}),
            "suspected_abuse": True,
            "manual_review": True,
            "reason": str(reason or "security_flag"),
            "module_code": (str(module_code).upper() if module_code else None),
            "actor": str(actor or "unknown"),
            "request_path": str(request_path or ""),
            "request_method": str(request_method or "").upper(),
        }
        behavior.updated_at = now

        return {
            "tenant_id": tenant_id,
            "suspicion_count": int(behavior.suspicion_count),
            "last_suspicion_at": behavior.last_suspicion_at.isoformat() if behavior.last_suspicion_at else None,
        }

    def tenant_status(self, db: Session, tenant_id: str) -> dict:
        return self.verify_leases_vs_heartbeats(db=db, tenant_id=tenant_id)

    def lease_device(self, db: Session, *, tenant_id: str, user_id: str, device_id: str, device_class: str) -> dict:
        now = self._now()
        row = (
            db.query(DeviceLease)
            .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.user_id == user_id)
            .first()
        )
        replaced = False

        # Seat limit check only when consuming a seat for an inactive/new user.
        if row is None or row.is_active is False:
            licensing_service.assert_seat_available(db, tenant_id=tenant_id, user_id=user_id)

        if row is None:
            row = DeviceLease(
                tenant_id=tenant_id,
                user_id=user_id,
                device_id=device_id,
                device_class=device_class,
                is_active=True,
                leased_at=now,
                last_seen_at=now,
            )
            db.add(row)
        else:
            if row.device_id != device_id or row.device_class != device_class:
                replaced = True
            row.device_id = device_id
            row.device_class = device_class
            row.is_active = True
            row.last_seen_at = now
            if row.leased_at is None:
                row.leased_at = now

        db.commit()

        entitlement = licensing_service.resolve_core_entitlement(db, tenant_id)
        active_users = licensing_service.count_active_leased_users(db, tenant_id)

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device_id": device_id,
            "device_class": device_class,
            "replaced_previous": replaced,
            "leased_at": row.leased_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "core_plan_code": entitlement.get("plan_code"),
            "core_seat_limit": entitlement.get("seat_limit"),
            "active_leased_users": active_users,
        }

    def get_lease(self, db: Session, *, tenant_id: str, user_id: str) -> dict:
        row = (
            db.query(DeviceLease)
            .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.user_id == user_id, DeviceLease.is_active == True)  # noqa: E712
            .first()
        )
        if row is None:
            return {"ok": True, "lease": None}
        return {
            "ok": True,
            "lease": {
                "tenant_id": row.tenant_id,
                "user_id": row.user_id,
                "device_id": row.device_id,
                "device_class": row.device_class,
                "leased_at": row.leased_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
            },
        }
