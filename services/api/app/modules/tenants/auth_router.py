from fastapi import APIRouter, HTTPException

from app.core.auth import create_access_token
from app.core.settings import get_settings
from app.core.startup_security import is_prod_env

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-token")
def dev_token(payload: dict | None = None) -> dict:
    settings = get_settings()
    if not bool(settings.auth_dev_token_enabled):
        raise HTTPException(status_code=404, detail="not_found")
    if is_prod_env(settings.app_env):
        raise HTTPException(status_code=403, detail="dev_token_disabled_in_prod")

    body = payload or {}

    sub = str(body.get("sub") or "").strip().lower()
    roles_raw = body.get("roles")
    tenant_id = str(body.get("tenant_id") or "").strip()

    if not sub:
        raise HTTPException(status_code=400, detail="sub_required")
    if not isinstance(roles_raw, list) or not roles_raw:
        raise HTTPException(status_code=400, detail="roles_required")

    roles: list[str] = []
    for value in roles_raw:
        role = str(value or "").strip().upper()
        if role and role not in roles:
            roles.append(role)
    if not roles:
        raise HTTPException(status_code=400, detail="roles_required")

    if "SUPERADMIN" not in roles and not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")

    claims = {
        "sub": sub,
        "roles": roles,
        "tenant_id": tenant_id,
    }
    if body.get("support_tenant_id") is not None:
        claims["support_tenant_id"] = body.get("support_tenant_id")
    if body.get("support_session_id") is not None:
        claims["support_session_id"] = body.get("support_session_id")
    if body.get("support_request_id") is not None:
        claims["support_request_id"] = body.get("support_request_id")

    token = create_access_token(claims)
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "example_auth_header": f"Bearer {token}",
    }