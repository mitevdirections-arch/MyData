from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import require_claims
from app.db.session import get_db_session
from app.modules.guard.service import service as guard_service
from app.modules.licensing.service import service as licensing_service


def require_module_entitlement(module_code: str) -> Callable[..., dict[str, Any]]:
    expected = str(module_code or "").strip().upper()
    if not expected:
        raise ValueError("module_code_required")

    def _dep(
        request: Request,
        claims: dict[str, Any] = Depends(require_claims),
        db: Session = Depends(get_db_session),
    ) -> dict[str, Any]:
        roles = set(claims.get("roles") or [])
        if "SUPERADMIN" in roles:
            return {
                "allowed": True,
                "module_code": expected,
                "reason": "superadmin_bypass",
                "source": {"role": "SUPERADMIN"},
                "valid_to": None,
            }

        tenant_id = str(claims.get("tenant_id") or "").strip()
        actor = str(claims.get("sub") or "unknown")
        if not tenant_id:
            raise HTTPException(status_code=403, detail="missing_tenant_context")

        entitlement = licensing_service.resolve_module_entitlement(db, tenant_id=tenant_id, module_code=expected)
        if bool(entitlement.get("allowed")):
            return entitlement

        guard_service.record_security_flag(
            db,
            tenant_id=tenant_id,
            reason="module_license_missing",
            module_code=expected,
            actor=actor,
            request_path=request.url.path,
            request_method=request.method,
        )
        write_audit(
            db,
            action="security.module_entitlement_denied",
            actor=actor,
            tenant_id=tenant_id,
            target=request.url.path,
            metadata={
                "module_code": expected,
                "method": request.method,
                "reason": entitlement.get("reason") or "module_license_required",
            },
        )
        db.commit()
        raise HTTPException(status_code=402, detail="module_license_required")

    return _dep