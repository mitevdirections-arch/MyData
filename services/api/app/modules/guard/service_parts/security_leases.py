from __future__ import annotations

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.models import AuditLog, DeviceLease
from app.modules.licensing.service import service as licensing_service


DEVICE_CLASS_DESKTOP = "desktop"
DEVICE_CLASS_MOBILE = "mobile"
VALID_DEVICE_CLASSES = {DEVICE_CLASS_DESKTOP, DEVICE_CLASS_MOBILE}

DEVICE_STATE_ACTIVE = "ACTIVE"
DEVICE_STATE_PAUSED = "PAUSED"
DEVICE_STATE_BACKGROUND_REACHABLE = "BACKGROUND_REACHABLE"
DEVICE_STATE_LOGGED_OUT = "LOGGED_OUT"
DEVICE_STATE_REVOKED = "REVOKED"
VALID_DEVICE_STATES = {
    DEVICE_STATE_ACTIVE,
    DEVICE_STATE_PAUSED,
    DEVICE_STATE_BACKGROUND_REACHABLE,
    DEVICE_STATE_LOGGED_OUT,
    DEVICE_STATE_REVOKED,
}


class GuardSecurityLeaseMixin:
    def _runtime_safe_non_active_state(self, row: DeviceLease) -> str:
        current = str(row.state or "").strip().upper()
        if current in {
            DEVICE_STATE_PAUSED,
            DEVICE_STATE_BACKGROUND_REACHABLE,
            DEVICE_STATE_LOGGED_OUT,
            DEVICE_STATE_REVOKED,
        }:
            return current
        return DEVICE_STATE_BACKGROUND_REACHABLE if str(row.device_class or "").strip().lower() == DEVICE_CLASS_MOBILE else DEVICE_STATE_PAUSED

    def _runtime_normalize_user_rows(self, db: Session, *, tenant_id: str, user_id: str, actor: str) -> int:
        now = self._now()
        rows = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
            )
            .all()
        )
        if not rows:
            return 0

        active_candidates = [
            row
            for row in rows
            if str(row.state or "").strip().upper() == DEVICE_STATE_ACTIVE or bool(row.is_active)
        ]
        active_candidates.sort(
            key=lambda row: (
                row.last_live_at or row.last_seen_at or row.state_changed_at or row.leased_at or now,
                row.leased_at or now,
                str(row.id),
            ),
            reverse=True,
        )
        winner_id = active_candidates[0].id if active_candidates else None

        changed = 0
        for row in rows:
            current_state = str(row.state or "").strip().upper()
            if current_state not in VALID_DEVICE_STATES:
                current_state = DEVICE_STATE_ACTIVE if bool(row.is_active) else DEVICE_STATE_LOGGED_OUT

            target_state = current_state
            if winner_id is not None and row.id == winner_id:
                target_state = DEVICE_STATE_ACTIVE
            elif winner_id is not None and (
                current_state == DEVICE_STATE_ACTIVE or bool(row.is_active)
            ):
                target_state = self._runtime_safe_non_active_state(row)

            target_is_active = target_state == DEVICE_STATE_ACTIVE
            if str(row.state or "").strip().upper() != target_state or bool(row.is_active) != target_is_active:
                prev = str(row.state or "").strip().upper() or None
                self._set_device_state(row, new_state=target_state, now=now)
                self._audit_device_transition(
                    db,
                    tenant_id=tenant_id,
                    actor=actor,
                    user_id=user_id,
                    device_id=row.device_id,
                    device_class=row.device_class,
                    from_state=prev,
                    to_state=row.state,
                    reason="RUNTIME_STATE_NORMALIZE",
                )
                changed += 1

        if changed > 0:
            db.flush()
        return changed

    def _commit_device_transition(self, db: Session) -> None:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError("DEVICE_STATE_CONFLICT_RETRY") from exc

    def _normalize_device_id(self, device_id: str | None) -> str:
        val = str(device_id or "").strip()
        if not val:
            raise ValueError("device_id_required")
        return val

    def _normalize_device_class(self, device_class: str | None) -> str:
        val = str(device_class or DEVICE_CLASS_DESKTOP).strip().lower()
        if val not in VALID_DEVICE_CLASSES:
            raise ValueError("device_class_invalid")
        return val

    def _state_for_device_class_when_demoted(self, active_device_class: str) -> str:
        if active_device_class == DEVICE_CLASS_MOBILE:
            return DEVICE_STATE_PAUSED
        return DEVICE_STATE_BACKGROUND_REACHABLE

    def _is_active_row(self, row: DeviceLease) -> bool:
        return bool(row.is_active) and str(row.state or "").strip().upper() == DEVICE_STATE_ACTIVE

    def _serialize_lease(self, row: DeviceLease) -> dict:
        return {
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "device_id": row.device_id,
            "device_class": row.device_class,
            "state": row.state,
            "is_active": bool(row.is_active),
            "leased_at": row.leased_at.isoformat() if row.leased_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "last_live_at": row.last_live_at.isoformat() if row.last_live_at else None,
            "state_changed_at": row.state_changed_at.isoformat() if row.state_changed_at else None,
            "paused_at": row.paused_at.isoformat() if row.paused_at else None,
            "background_reachable_at": row.background_reachable_at.isoformat() if row.background_reachable_at else None,
            "logged_out_at": row.logged_out_at.isoformat() if row.logged_out_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }

    def _set_device_state(self, row: DeviceLease, *, new_state: str, now) -> None:
        state = str(new_state or "").strip().upper()
        if state not in VALID_DEVICE_STATES:
            raise ValueError("device_state_invalid")

        row.state = state
        row.state_changed_at = now
        row.is_active = state == DEVICE_STATE_ACTIVE
        row.last_seen_at = now

        if state == DEVICE_STATE_ACTIVE:
            row.last_live_at = now
        elif state == DEVICE_STATE_PAUSED:
            row.paused_at = now
        elif state == DEVICE_STATE_BACKGROUND_REACHABLE:
            row.background_reachable_at = now
            row.last_live_at = now
        elif state == DEVICE_STATE_LOGGED_OUT:
            row.logged_out_at = now
            row.last_live_at = now
        elif state == DEVICE_STATE_REVOKED:
            row.revoked_at = now
            row.last_live_at = now

    def _audit_device_transition(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        user_id: str,
        device_id: str,
        device_class: str,
        from_state: str | None,
        to_state: str | None,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        db.add(
            AuditLog(
                action="guard.device_state_transition",
                actor=str(actor or "unknown"),
                tenant_id=tenant_id,
                target=f"user/{user_id}",
                metadata_json={
                    "user_id": user_id,
                    "device_id": device_id,
                    "device_class": device_class,
                    "from_state": str(from_state or "").upper() or None,
                    "to_state": str(to_state or "").upper() or None,
                    "reason": str(reason or "state_transition"),
                    **(dict(metadata or {})),
                },
            )
        )

    def _lazy_auto_logout_paused_desktop(self, db: Session, *, tenant_id: str, user_id: str, actor: str) -> int:
        now = self._now()
        timeout_min = max(1, int(get_settings().guard_device_paused_desktop_auto_logout_minutes))
        cutoff = now - timedelta(minutes=timeout_min)

        rows = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_class == DEVICE_CLASS_DESKTOP,
                DeviceLease.state == DEVICE_STATE_PAUSED,
                DeviceLease.paused_at.isnot(None),
                DeviceLease.paused_at <= cutoff,
            )
            .all()
        )

        changed = 0
        for row in rows:
            prev = str(row.state or "").upper()
            self._set_device_state(row, new_state=DEVICE_STATE_LOGGED_OUT, now=now)
            self._audit_device_transition(
                db,
                tenant_id=tenant_id,
                actor=actor,
                user_id=user_id,
                device_id=row.device_id,
                device_class=row.device_class,
                from_state=prev,
                to_state=row.state,
                reason="AUTO_LOGOUT_PAUSED_DESKTOP_TIMEOUT",
                metadata={"paused_timeout_minutes": timeout_min},
            )
            changed += 1

        if changed > 0:
            db.flush()
        return changed

    def _demote_peer_device(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        active_device_class: str,
        active_device_id: str,
        actor: str,
    ) -> None:
        target_state = self._state_for_device_class_when_demoted(active_device_class)
        now = self._now()

        peer_rows = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_class != active_device_class,
            )
            .all()
        )

        for peer in peer_rows:
            prev = str(peer.state or "").upper()
            if prev == DEVICE_STATE_REVOKED:
                continue
            if peer.device_id == active_device_id and peer.device_class == active_device_class:
                continue
            if prev == target_state and peer.is_active is False:
                continue

            self._set_device_state(peer, new_state=target_state, now=now)
            self._audit_device_transition(
                db,
                tenant_id=tenant_id,
                actor=actor,
                user_id=user_id,
                device_id=peer.device_id,
                device_class=peer.device_class,
                from_state=prev,
                to_state=peer.state,
                reason="PEER_DEVICE_DEMOTED",
                metadata={"activated_device_class": active_device_class, "activated_device_id": active_device_id},
            )

    def _claim_or_get_slot(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        device_id: str,
        device_class: str,
        actor: str,
        reason: str,
    ) -> tuple[DeviceLease, bool]:
        now = self._now()
        slot = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_class == device_class,
            )
            .first()
        )

        replaced = False
        if slot is None:
            slot = DeviceLease(
                tenant_id=tenant_id,
                user_id=user_id,
                device_id=device_id,
                device_class=device_class,
                state=DEVICE_STATE_ACTIVE,
                is_active=True,
                leased_at=now,
                last_seen_at=now,
                last_live_at=now,
                state_changed_at=now,
            )
            db.add(slot)
            db.flush()
            self._audit_device_transition(
                db,
                tenant_id=tenant_id,
                actor=actor,
                user_id=user_id,
                device_id=device_id,
                device_class=device_class,
                from_state=None,
                to_state=DEVICE_STATE_ACTIVE,
                reason=reason,
            )
            return slot, replaced

        if str(slot.state or "").upper() == DEVICE_STATE_REVOKED:
            raise ValueError("device_revoked")

        prev = str(slot.state or "").upper()
        if slot.device_id != device_id:
            replaced = True
        slot.device_id = device_id
        if slot.leased_at is None:
            slot.leased_at = now
        self._set_device_state(slot, new_state=DEVICE_STATE_ACTIVE, now=now)
        self._audit_device_transition(
            db,
            tenant_id=tenant_id,
            actor=actor,
            user_id=user_id,
            device_id=device_id,
            device_class=device_class,
            from_state=prev,
            to_state=slot.state,
            reason=reason,
            metadata={"slot_replaced": replaced},
        )
        return slot, replaced

    def claim_device_slot(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        device_id: str,
        device_class: str,
        actor: str,
    ) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        normalized_device_class = self._normalize_device_class(device_class)
        actor_val = str(actor or user_id or "unknown")

        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=actor_val)
        self._lazy_auto_logout_paused_desktop(db, tenant_id=tenant_id, user_id=user_id, actor=actor_val)

        active_before = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.state == DEVICE_STATE_ACTIVE,
                DeviceLease.is_active == True,  # noqa: E712
            )
            .count()
        )
        if int(active_before) <= 0:
            licensing_service.assert_seat_available(db, tenant_id=tenant_id, user_id=user_id, exclude_user_id=user_id)

        self._demote_peer_device(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            active_device_class=normalized_device_class,
            active_device_id=normalized_device_id,
            actor=actor_val,
        )
        slot, replaced = self._claim_or_get_slot(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            device_id=normalized_device_id,
            device_class=normalized_device_class,
            actor=actor_val,
            reason="CLAIM_SLOT",
        )
        self._commit_device_transition(db)

        entitlement = licensing_service.resolve_core_entitlement(db, tenant_id)
        active_users = licensing_service.count_active_leased_users(db, tenant_id)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device_id": normalized_device_id,
            "device_class": normalized_device_class,
            "state": slot.state,
            "replaced_previous": replaced,
            "leased_at": slot.leased_at.isoformat() if slot.leased_at else None,
            "last_seen_at": slot.last_seen_at.isoformat() if slot.last_seen_at else None,
            "core_plan_code": entitlement.get("plan_code"),
            "core_seat_limit": entitlement.get("seat_limit"),
            "active_leased_users": active_users,
        }

    def activate_device(self, db: Session, *, tenant_id: str, user_id: str, device_id: str, actor: str) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        actor_val = str(actor or user_id or "unknown")

        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=actor_val)
        self._lazy_auto_logout_paused_desktop(db, tenant_id=tenant_id, user_id=user_id, actor=actor_val)
        row = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id == normalized_device_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("device_not_leased")
        if str(row.state or "").upper() == DEVICE_STATE_REVOKED:
            raise ValueError("DEVICE_REVOKED")
        if str(row.state or "").upper() == DEVICE_STATE_LOGGED_OUT:
            raise ValueError("DEVICE_LOGGED_OUT")

        active_before = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.state == DEVICE_STATE_ACTIVE,
                DeviceLease.is_active == True,  # noqa: E712
            )
            .count()
        )
        if int(active_before) <= 0:
            licensing_service.assert_seat_available(db, tenant_id=tenant_id, user_id=user_id, exclude_user_id=user_id)

        self._demote_peer_device(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            active_device_class=str(row.device_class or "").strip().lower(),
            active_device_id=row.device_id,
            actor=actor_val,
        )

        prev = str(row.state or "").upper()
        now = self._now()
        self._set_device_state(row, new_state=DEVICE_STATE_ACTIVE, now=now)
        self._audit_device_transition(
            db,
            tenant_id=tenant_id,
            actor=actor_val,
            user_id=user_id,
            device_id=row.device_id,
            device_class=row.device_class,
            from_state=prev,
            to_state=row.state,
            reason="MANUAL_ACTIVATE",
        )
        self._commit_device_transition(db)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": self._serialize_lease(row),
            "non_blocking": True,
        }

    def logout_device(self, db: Session, *, tenant_id: str, user_id: str, device_id: str, actor: str) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        actor_val = str(actor or user_id or "unknown")
        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=actor_val)
        row = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id == normalized_device_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("device_not_leased")

        prev = str(row.state or "").upper()
        now = self._now()
        self._set_device_state(row, new_state=DEVICE_STATE_LOGGED_OUT, now=now)
        self._audit_device_transition(
            db,
            tenant_id=tenant_id,
            actor=actor_val,
            user_id=user_id,
            device_id=row.device_id,
            device_class=row.device_class,
            from_state=prev,
            to_state=row.state,
            reason="MANUAL_LOGOUT",
        )
        self._commit_device_transition(db)

        next_candidate = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id != normalized_device_id,
                DeviceLease.state.in_([DEVICE_STATE_PAUSED, DEVICE_STATE_BACKGROUND_REACHABLE]),
            )
            .order_by(DeviceLease.state_changed_at.desc())
            .first()
        )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": self._serialize_lease(row),
            "next_active_candidate": self._serialize_lease(next_candidate) if next_candidate is not None else None,
            "non_blocking": True,
        }

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
        return self.claim_device_slot(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            device_id=device_id,
            device_class=device_class,
            actor=user_id,
        )

    def get_lease(self, db: Session, *, tenant_id: str, user_id: str) -> dict:
        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)
        self._lazy_auto_logout_paused_desktop(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)
        rows = (
            db.query(DeviceLease)
            .filter(DeviceLease.tenant_id == tenant_id, DeviceLease.user_id == user_id)
            .order_by(DeviceLease.device_class.asc(), DeviceLease.state_changed_at.desc())
            .all()
        )
        active = next((x for x in rows if self._is_active_row(x)), None)
        return {
            "ok": True,
            "lease": (self._serialize_lease(active) if active is not None else None),
            "slots": [self._serialize_lease(x) for x in rows],
        }

    def get_device_status(self, db: Session, *, tenant_id: str, user_id: str, device_id: str) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)
        self._lazy_auto_logout_paused_desktop(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)

        row = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id == normalized_device_id,
            )
            .first()
        )
        active = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.state == DEVICE_STATE_ACTIVE,
                DeviceLease.is_active == True,  # noqa: E712
            )
            .first()
        )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": (self._serialize_lease(row) if row is not None else None),
            "active_device": (self._serialize_lease(active) if active is not None else None),
        }

    def revoke_device(self, db: Session, *, tenant_id: str, user_id: str, device_id: str, actor: str) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=str(actor or user_id))
        row = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id == normalized_device_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("device_not_leased")

        prev = str(row.state or "").upper()
        now = self._now()
        self._set_device_state(row, new_state=DEVICE_STATE_REVOKED, now=now)
        self._audit_device_transition(
            db,
            tenant_id=tenant_id,
            actor=str(actor or "unknown"),
            user_id=user_id,
            device_id=row.device_id,
            device_class=row.device_class,
            from_state=prev,
            to_state=row.state,
            reason="MANUAL_REVOKE",
        )
        self._commit_device_transition(db)
        return {"ok": True, "tenant_id": tenant_id, "user_id": user_id, "device": self._serialize_lease(row)}

    def assert_request_device_active(self, db: Session, *, tenant_id: str, user_id: str, device_id: str) -> dict:
        normalized_device_id = self._normalize_device_id(device_id)
        self._runtime_normalize_user_rows(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)
        self._lazy_auto_logout_paused_desktop(db, tenant_id=tenant_id, user_id=user_id, actor=user_id)
        row = (
            db.query(DeviceLease)
            .filter(
                DeviceLease.tenant_id == tenant_id,
                DeviceLease.user_id == user_id,
                DeviceLease.device_id == normalized_device_id,
            )
            .first()
        )
        if row is None:
            raise ValueError("DEVICE_NOT_ACTIVE")

        state = str(row.state or "").strip().upper()
        if state == DEVICE_STATE_REVOKED:
            raise ValueError("DEVICE_REVOKED")
        if state == DEVICE_STATE_LOGGED_OUT:
            raise ValueError("DEVICE_LOGGED_OUT")
        if state != DEVICE_STATE_ACTIVE or row.is_active is not True:
            raise ValueError("DEVICE_NOT_ACTIVE")

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device_id": row.device_id,
            "device_class": row.device_class,
            "state": row.state,
            "non_blocking": True,
        }
