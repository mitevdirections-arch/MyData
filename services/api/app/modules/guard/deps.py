from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import require_claims
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.modules.guard.service import service


async def require_guard_bot_signature(
    request: Request,
    claims: dict[str, Any] = Depends(require_claims),
    db: Session = Depends(get_db_session),
    x_bot_id: str | None = Header(default=None, alias="X-Bot-ID"),
    x_bot_key_version: str | None = Header(default=None, alias="X-Bot-Key-Version"),
    x_bot_timestamp: str | None = Header(default=None, alias="X-Bot-Timestamp"),
    x_bot_nonce: str | None = Header(default=None, alias="X-Bot-Nonce"),
    x_bot_signature: str | None = Header(default=None, alias="X-Bot-Signature"),
) -> dict[str, Any]:
    s = get_settings()
    if not bool(s.guard_bot_signature_required):
        return {"ok": True, "mode": "signature_optional"}

    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    missing = []
    if not x_bot_id:
        missing.append("X-Bot-ID")
    if not x_bot_key_version:
        missing.append("X-Bot-Key-Version")
    if not x_bot_timestamp:
        missing.append("X-Bot-Timestamp")
    if not x_bot_nonce:
        missing.append("X-Bot-Nonce")
    if not x_bot_signature:
        missing.append("X-Bot-Signature")

    if missing:
        raise HTTPException(status_code=401, detail=f"bot_signature_headers_missing:{','.join(missing)}")

    try:
        key_version = int(str(x_bot_key_version).strip())
        timestamp = int(str(x_bot_timestamp).strip())
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="bot_signature_header_invalid") from exc

    body = await request.body()

    try:
        out = service.verify_bot_signature(
            db,
            tenant_id=tenant_id,
            bot_id=str(x_bot_id),
            key_version=key_version,
            timestamp=timestamp,
            nonce=str(x_bot_nonce),
            signature=str(x_bot_signature),
            method=request.method,
            path=request.url.path,
            body_bytes=body,
            actor=str(claims.get("sub") or "guard-bot"),
        )
    except ValueError as exc:
        detail = str(exc)
        code = 423 if detail == "bot_credential_locked" else 401
        raise HTTPException(status_code=code, detail=detail) from exc

    return out