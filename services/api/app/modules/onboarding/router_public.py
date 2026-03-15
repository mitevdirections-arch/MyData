from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.db.session import get_db_session
from app.modules.onboarding.schemas import OnboardingPublicCreateRequest
from app.modules.onboarding.service import service

router = APIRouter(prefix="/public/onboarding", tags=["public.onboarding"])


@router.post("/applications")
def create_application(payload: OnboardingPublicCreateRequest, db: Session = Depends(get_db_session)) -> dict:
    out = service.create_public_application(db=db, payload=payload.model_dump())
    write_audit(
        db,
        action="onboarding.public_create",
        actor="public",
        tenant_id=None,
        target="onboarding/application",
        metadata={"application_id": out.get("id"), "country_code": payload.country_code},
    )
    db.commit()
    return {"ok": True, "application": out}
