from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import GuardBotCheck, Tenant
from app.modules.licensing.service import service as licensing_service


class GuardBotChecksMixin:
    def verify_license_snapshot(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        device_id: str,
        active_license_codes: list[str],
    ) -> dict:
        out = licensing_service.verify_client_license_snapshot(
            db,
            tenant_id=tenant_id,
            active_license_codes=active_license_codes,
        )

        if not bool(out.get("ok")):
            self.record_security_flag(
                db,
                tenant_id=tenant_id,
                reason="license_snapshot_mismatch",
                module_code=None,
                actor=actor,
                request_path="/guard/license-snapshot",
                request_method="POST",
            )

        out["device_id"] = device_id
        out["reported_at"] = self._now().isoformat()
        return out


    def bot_check_tenant(
        self,
        db: Session,
        *,
        tenant_id: str,
        bot_id: str = "guard-bot",
        mode: str = "SCHEDULED",
        run_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        now = self._now()
        verification = self.verify_leases_vs_heartbeats(db, tenant_id=tenant_id)
        summary = verification.get("summary") or {}

        rid = uuid.UUID(run_id) if run_id else uuid.uuid4()
        row = GuardBotCheck(
            run_id=rid,
            tenant_id=tenant_id,
            bot_id=str(bot_id or "guard-bot")[:128],
            mode=str(mode or "SCHEDULED")[:32],
            state=str(verification.get("state") or "ALLOW"),
            missing_heartbeat=int(summary.get("missing_heartbeat") or 0),
            stale_heartbeat=int(summary.get("stale_heartbeat") or 0),
            bad_status=int(summary.get("bad_status") or 0),
            stale_enforced=bool(verification.get("stale_enforced")),
            summary_json=summary,
            notes=(str(notes)[:512] if notes else None),
            checked_at=now,
        )
        db.add(row)

        if row.state == "RESTRICT":
            behavior = self._get_or_create_behavior(db, tenant_id)
            behavior.good_since = now
            behavior.suspicion_count = int(behavior.suspicion_count) + 1
            behavior.last_suspicion_at = now
            behavior.last_flags_json = {
                **(behavior.last_flags_json or {}),
                "manual_review": True,
                "bot_suspected_issue": True,
                "bot_mode": row.mode,
            }
            behavior.updated_at = now

        db.commit()

        return {
            "ok": True,
            "check_id": str(row.id),
            "run_id": str(row.run_id) if row.run_id else None,
            "tenant_id": tenant_id,
            "state": row.state,
            "summary": summary,
        }

    def bot_sweep_once(
        self,
        db: Session,
        *,
        actor: str,
        tenant_id: str | None = None,
        limit: int = 200,
        mode: str = "SCHEDULED",
    ) -> dict:
        run_id = str(uuid.uuid4())
        if tenant_id:
            tenants = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).all()  # noqa: E712
        else:
            tenants = (
                db.query(Tenant)
                .filter(Tenant.is_active == True)  # noqa: E712
                .order_by(Tenant.created_at.asc())
                .limit(max(1, min(int(limit), 1000)))
                .all()
            )

        items: list[dict] = []
        restrict = 0
        for t in tenants:
            one = self.bot_check_tenant(
                db,
                tenant_id=t.id,
                bot_id="guard-bot",
                mode=mode,
                run_id=run_id,
                notes=f"sweep_by={actor}",
            )
            items.append(one)
            if one.get("state") == "RESTRICT":
                restrict += 1

        return {
            "ok": True,
            "run_id": run_id,
            "requested_by": actor,
            "checked_tenants": len(items),
            "restrict_tenants": restrict,
            "allow_tenants": len(items) - restrict,
            "items": items,
        }

    def list_bot_checks(self, db: Session, *, tenant_id: str | None = None, limit: int = 200) -> list[dict]:
        q = db.query(GuardBotCheck)
        if tenant_id:
            q = q.filter(GuardBotCheck.tenant_id == tenant_id)

        rows = q.order_by(GuardBotCheck.checked_at.desc()).limit(max(1, min(int(limit), 1000))).all()
        return [
            {
                "id": str(x.id),
                "run_id": str(x.run_id) if x.run_id else None,
                "tenant_id": x.tenant_id,
                "bot_id": x.bot_id,
                "mode": x.mode,
                "state": x.state,
                "missing_heartbeat": int(x.missing_heartbeat),
                "stale_heartbeat": int(x.stale_heartbeat),
                "bad_status": int(x.bad_status),
                "stale_enforced": bool(x.stale_enforced),
                "summary": x.summary_json or {},
                "notes": x.notes,
                "checked_at": x.checked_at.isoformat(),
            }
            for x in rows
        ]

