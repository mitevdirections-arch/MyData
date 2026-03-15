from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_superadmin
from app.db.session import get_db_session
from app.modules.onboarding.service import service

router = APIRouter(prefix="/admin/onboarding", tags=["admin.onboarding"])


@router.get("/applications")
def list_applications(
    limit: int = 50,
    offset: int = 0,
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict:
    out = service.list_applications(db=db, limit=limit, offset=offset)
    out["requested_by"] = claims.get("sub", "unknown")
    return out
