from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_superadmin_permission
from app.db.session import get_db_session
from app.modules.profile.service import service

super_router = APIRouter()


@super_router.get("/tenants-overview")
def tenants_overview(
    claims: dict[str, Any] = Depends(require_superadmin_permission("TENANTS.READ")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return service.superadmin_platform_overview(db, actor=str(claims.get("sub") or "unknown"))
