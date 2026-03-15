from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_superadmin
from app.db.session import get_db_session
from app.modules.provisioning.service import service

router = APIRouter(prefix="/superadmin/provisioning", tags=["superadmin.provisioning"])


@router.post("/tenant/run")
def run_tenant_provisioning(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    actor = str(claims.get("sub") or "unknown")
    try:
        return service.run_tenant_provisioning(db, payload=payload, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
