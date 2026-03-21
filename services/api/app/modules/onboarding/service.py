from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import OnboardingApplication
from app.modules.country_engine.registry import get_country_template
from app.modules.licensing.core_catalog import canonical_plan_code, recommended_plan_for_seats
from app.modules.provisioning.service import service as provisioning_service


def _plan_for_seats(seats: int) -> str:
    return recommended_plan_for_seats(int(seats))


class OnboardingService:
    def _to_item(self, row: OnboardingApplication) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "status": row.status,
            "legal_name": row.legal_name,
            "country_code": row.country_code,
            "seat_count": int(row.seat_count),
            "core_plan_code": canonical_plan_code(row.core_plan_code, default=_plan_for_seats(int(row.seat_count))),
            "created_at": row.created_at.isoformat(),
        }

    def create_public_application(self, db: Session, payload: dict) -> dict:
        cc = str(payload.get("country_code") or "").strip().upper()
        tpl = get_country_template(cc)
        seats = int(payload.get("seat_count") or 1)
        core_plan = _plan_for_seats(seats)

        app = OnboardingApplication(
            status="SUBMITTED",
            legal_name=str(payload.get("legal_name") or "").strip(),
            country_code=cc,
            contact_email=str(payload.get("contact_email") or "").strip().lower(),
            seat_count=seats,
            core_plan_code=core_plan,
            default_locale=tpl.defaults.default_locale,
            default_time_zone=tpl.defaults.default_time_zone,
            date_style=tpl.defaults.date_style.value,
            time_style=tpl.defaults.time_style.value,
            unit_system=tpl.defaults.unit_system.value,
            payload_json=payload,
        )
        db.add(app)
        db.commit()
        db.refresh(app)

        return {
            "id": str(app.id),
            "status": app.status,
            "core_plan_code": core_plan,
            "country_defaults": {
                "default_locale": app.default_locale,
                "default_time_zone": app.default_time_zone,
                "date_style": app.date_style,
                "time_style": app.time_style,
                "unit_system": app.unit_system,
            },
        }

    def list_applications(self, db: Session, limit: int = 50, offset: int = 0) -> dict:
        q = db.query(OnboardingApplication).order_by(OnboardingApplication.created_at.desc())
        items = q.offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
        return {
            "ok": True,
            "items": [self._to_item(x) for x in items],
        }

    def approve_application_and_provision(self, db: Session, *, application_id: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            aid = UUID(str(application_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("application_id_invalid") from exc

        app = db.query(OnboardingApplication).filter(OnboardingApplication.id == aid).first()
        if app is None:
            raise ValueError("application_not_found")
        status = str(app.status or "").upper()
        if status == "APPROVED":
            raise ValueError("application_already_approved")
        if status == "APPROVING":
            raise ValueError("application_approval_in_progress")
        if status != "SUBMITTED":
            raise ValueError("application_not_submitted")

        # CAS-style status transition prevents duplicate provisioning starts on concurrent approvals.
        locked_rows = (
            db.query(OnboardingApplication)
            .filter(
                OnboardingApplication.id == aid,
                OnboardingApplication.status == "SUBMITTED",
            )
            .update(
                {OnboardingApplication.status: "APPROVING"},
                synchronize_session=False,
            )
        )
        if int(locked_rows or 0) != 1:
            db.rollback()
            fresh = db.query(OnboardingApplication).filter(OnboardingApplication.id == aid).first()
            if fresh is None:
                raise ValueError("application_not_found")
            fresh_status = str(fresh.status or "").upper()
            if fresh_status == "APPROVED":
                raise ValueError("application_already_approved")
            if fresh_status == "APPROVING":
                raise ValueError("application_approval_in_progress")
            raise ValueError("application_not_submitted")

        db.commit()
        app = db.query(OnboardingApplication).filter(OnboardingApplication.id == aid).first()
        if app is None:
            raise ValueError("application_not_found")

        body = dict(payload or {})
        tenant_id = str(body.get("tenant_id") or "").strip()
        if not tenant_id:
            raise ValueError("tenant_id_required")

        app_payload = dict(app.payload_json or {})
        admin_block = dict(body.get("admin") or {})
        admin_email = str(admin_block.get("email") or app.contact_email or "").strip().lower() or None
        admin_user_id = str(admin_block.get("user_id") or admin_email or "").strip()
        if not admin_user_id:
            raise ValueError("admin_user_id_required")

        requested_core = str(body.get("core_plan_code") or app.core_plan_code or "").strip()
        core_plan_code = canonical_plan_code(
            requested_core,
            default=_plan_for_seats(int(app.seat_count)),
        )

        provisioning_payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "name": str(body.get("tenant_name") or app.legal_name or "").strip() or tenant_id,
            "vat_number": str(body.get("vat_number") or app_payload.get("vat_number") or "").strip() or None,
            "issuance": {
                "issue_startup": True,
                "admin_confirmed": True,
                "core_plan_code": core_plan_code,
            },
            "admin": {
                "user_id": admin_user_id,
                "email": admin_email,
                "display_name": str(admin_block.get("display_name") or app.legal_name or admin_user_id).strip(),
                "job_title": str(admin_block.get("job_title") or "Tenant Administrator").strip(),
            },
            "i18n": {
                "default_locale": app.default_locale,
                "fallback_locale": app.default_locale,
                "enabled_locales": [app.default_locale],
            },
        }

        try:
            provisioning_result = provisioning_service.run_tenant_provisioning(
                db,
                payload=provisioning_payload,
                actor=str(actor or "unknown"),
            )
        except Exception:
            # Release lock state to allow a safe retry by admin.
            app.status = "SUBMITTED"
            db.commit()
            db.refresh(app)
            raise

        app.status = "APPROVED"
        app.payload_json = {
            **app_payload,
            "approval": {
                "approved_by": str(actor or "unknown"),
                "tenant_id": tenant_id,
                "core_plan_code": core_plan_code,
            },
        }
        db.commit()
        db.refresh(app)

        return {
            "ok": True,
            "application": self._to_item(app),
            "provisioning": provisioning_result,
        }


service = OnboardingService()
