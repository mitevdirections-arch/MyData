from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import OnboardingApplication
from app.modules.country_engine.registry import get_country_template


def _plan_for_seats(seats: int) -> str:
    if seats <= 3:
        return "CORE_U3"
    if seats <= 5:
        return "CORE_U5"
    if seats <= 8:
        return "CORE_U8"
    if seats <= 13:
        return "CORE_U13"
    if seats <= 21:
        return "CORE_U21"
    if seats <= 34:
        return "CORE_U34"
    return "CORE_ENTERPRISE"


class OnboardingService:
    def create_public_application(self, db: Session, payload: dict) -> dict:
        cc = str(payload.get("country_code") or "").strip().upper()
        tpl = get_country_template(cc)

        app = OnboardingApplication(
            status="SUBMITTED",
            legal_name=str(payload.get("legal_name") or "").strip(),
            country_code=cc,
            contact_email=str(payload.get("contact_email") or "").strip().lower(),
            seat_count=int(payload.get("seat_count") or 1),
            core_plan_code=_plan_for_seats(int(payload.get("seat_count") or 1)),
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
            "core_plan_code": app.core_plan_code,
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
            "items": [
                {
                    "id": str(x.id),
                    "status": x.status,
                    "legal_name": x.legal_name,
                    "country_code": x.country_code,
                    "seat_count": x.seat_count,
                    "core_plan_code": x.core_plan_code,
                    "created_at": x.created_at.isoformat(),
                }
                for x in items
            ],
        }


service = OnboardingService()
