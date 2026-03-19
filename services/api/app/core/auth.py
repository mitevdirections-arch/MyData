from __future__ import annotations

import base64
from contextvars import ContextVar, Token
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import time
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.permissions import effective_permissions_from_claims, is_permission_allowed, normalize_permission
from app.core.settings import get_settings
from app.core.perf_profile import record_segment


class AuthError(HTTPException):
    def __init__(self, detail: str = "unauthorized") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


_CURRENT_CLAIMS: ContextVar[dict[str, Any] | None] = ContextVar("mydata_current_claims", default=None)
_REQUEST_AUTHZ_CACHE_ATTR = "_mydata_request_authz_cache"
_AUTH_CONTEXT_CLAIMS_ATTR = "claims"
_AUTH_CONTEXT_TOKEN_FP_ATTR = "_mydata_verified_bearer_token_fingerprint"


def _protected_envelope_breakdown_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_PROTECTED_ENVELOPE_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _request_authz_cache_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _claims_signature(claims: dict[str, Any]) -> tuple[str, str, str]:
    sub = str(claims.get("sub") or "").strip()
    tenant_id = str(claims.get("tenant_id") or "").strip()
    roles = sorted(str(x).strip().upper() for x in list(claims.get("roles") or []) if str(x).strip())
    return sub, tenant_id, "|".join(roles)


def _request_authz_cache_get(request: Request) -> dict[str, Any]:
    cache = getattr(request.state, _REQUEST_AUTHZ_CACHE_ATTR, None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(request.state, _REQUEST_AUTHZ_CACHE_ATTR, cache)
    return cache


def _single_verify_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_SINGLE_VERIFY", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _verified_claims_from_request_state(request: Request, token: str) -> dict[str, Any] | None:
    if not _single_verify_enabled():
        return None

    claims = getattr(request.state, _AUTH_CONTEXT_CLAIMS_ATTR, None)
    token_fp = getattr(request.state, _AUTH_CONTEXT_TOKEN_FP_ATTR, None)
    if not isinstance(claims, dict):
        return None
    if not isinstance(token_fp, str):
        return None
    if token_fp != _token_fingerprint(token):
        return None
    return claims


def set_current_claims(claims: dict[str, Any] | None) -> Token:
    return _CURRENT_CLAIMS.set(dict(claims or {}))


def reset_current_claims(token: Token) -> None:
    _CURRENT_CLAIMS.reset(token)


def get_current_claims() -> dict[str, Any] | None:
    claims = _CURRENT_CLAIMS.get()
    if not isinstance(claims, dict):
        return None
    return dict(claims)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(mac)


def create_access_token(claims: dict[str, Any], ttl_seconds: int | None = None) -> str:
    s = get_settings()
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else s.access_token_ttl_seconds
    header = {"alg": s.jwt_algorithm, "typ": "JWT"}
    body = {
        **claims,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": now,
        "exp": now + ttl,
    }

    h64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    b64 = _b64url_encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signed = f"{h64}.{b64}"
    sig = _sign(signed, s.jwt_secret)
    return f"{signed}.{sig}"


def verify_access_token(token: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        s = get_settings()
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthError("invalid_token_format")

        h64, b64, sig = parts
        expected = _sign(f"{h64}.{b64}", s.jwt_secret)
        if not hmac.compare_digest(sig, expected):
            raise AuthError("invalid_token_signature")

        try:
            body_raw = _b64url_decode(b64)
            claims = json.loads(body_raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AuthError("invalid_token_payload") from exc

        now = int(time.time())
        if int(claims.get("exp", 0)) < now:
            raise AuthError("token_expired")
        if claims.get("iss") != s.jwt_issuer:
            raise AuthError("invalid_issuer")
        if claims.get("aud") != s.jwt_audience:
            raise AuthError("invalid_audience")
        return claims
    finally:
        record_segment("token_verify_ms", (time.perf_counter() - started) * 1000.0)


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing_authorization")
    if not authorization.lower().startswith("bearer "):
        raise AuthError("invalid_authorization_scheme")
    return authorization.split(" ", 1)[1].strip()


def _require_superadmin_support_scope(claims: dict[str, Any], *, tenant_id: str) -> None:
    roles = set(claims.get("roles") or [])
    if "SUPERADMIN" not in roles:
        return

    support_tenant_id = str(claims.get("support_tenant_id") or "").strip()
    support_session_id = str(claims.get("support_session_id") or "").strip()
    if support_tenant_id != tenant_id or not support_session_id:
        raise HTTPException(status_code=403, detail="support_session_required_for_tenant_scope")

    try:
        sid = UUID(support_session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=403, detail="support_session_required_for_tenant_scope") from exc

    from app.db.models import SupportSession
    from app.db.session import get_session_factory

    db = get_session_factory()()
    now = datetime.now(timezone.utc)
    try:
        row = (
            db.query(SupportSession)
            .filter(
                SupportSession.id == sid,
                SupportSession.tenant_id == tenant_id,
                SupportSession.status == "ACTIVE",
                SupportSession.expires_at >= now,
            )
            .first()
        )
    finally:
        db.close()

    if row is None:
        raise HTTPException(status_code=403, detail="support_session_invalid_or_expired")


def _decode_step_up_secret(secret: str) -> bytes | None:
    raw = str(secret or "").strip().replace(" ", "")
    if not raw:
        return None
    try:
        return base64.b32decode(raw, casefold=True)
    except Exception:  # noqa: BLE001
        return None


def _totp_code(secret_bytes: bytes, counter: int, *, digits: int = 6) -> str:
    msg = int(counter).to_bytes(8, byteorder="big", signed=False)
    digest = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    val = ((digest[offset] & 0x7F) << 24) | ((digest[offset + 1] & 0xFF) << 16) | ((digest[offset + 2] & 0xFF) << 8) | (digest[offset + 3] & 0xFF)
    return str(val % (10**int(digits))).zfill(int(digits))


def is_superadmin_step_up_code_valid(code: str | None, *, now_ts: int | None = None) -> bool:
    s = get_settings()
    if not bool(s.superadmin_step_up_enabled):
        return True

    secret_bytes = _decode_step_up_secret(str(s.superadmin_step_up_totp_secret or ""))
    if secret_bytes is None:
        return False

    raw_code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(raw_code) != 6:
        return False

    period = max(15, int(s.superadmin_step_up_period_seconds))
    window = max(0, int(s.superadmin_step_up_window_steps))
    base_counter = int((int(now_ts) if now_ts is not None else int(time.time())) // period)

    for drift in range(-window, window + 1):
        expected = _totp_code(secret_bytes, base_counter + drift, digits=6)
        if hmac.compare_digest(raw_code, expected):
            return True

    return False


def require_claims(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    breakdown_enabled = _protected_envelope_breakdown_enabled()
    claims_prepare_started = time.perf_counter()

    token = _extract_bearer(authorization)
    claims = _verified_claims_from_request_state(request, token)
    token_verify_ms = 0.0
    if claims is None:
        token_verify_started = time.perf_counter()
        claims = verify_access_token(token)
        token_verify_ms = (time.perf_counter() - token_verify_started) * 1000.0
        setattr(request.state, _AUTH_CONTEXT_CLAIMS_ATTR, claims)
        setattr(request.state, _AUTH_CONTEXT_TOKEN_FP_ATTR, _token_fingerprint(token))

    # Defense-in-depth: optional tenant header must match token tenant.
    if x_tenant_id:
        token_tenant = str(claims.get("tenant_id") or "").strip()
        hdr_tenant = str(x_tenant_id or "").strip()
        if token_tenant and hdr_tenant and token_tenant != hdr_tenant:
            raise HTTPException(status_code=403, detail="tenant_context_mismatch")

    if breakdown_enabled:
        claims_prepare_total_ms = (time.perf_counter() - claims_prepare_started) * 1000.0
        record_segment("protected_token_verify_ms", max(0.0, float(token_verify_ms)))
        record_segment("protected_claims_prepare_ms", max(0.0, float(claims_prepare_total_ms - token_verify_ms)))

    set_current_claims(claims)
    return claims


def require_superadmin(claims: dict[str, Any] = Depends(require_claims)) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if "SUPERADMIN" not in roles:
        raise HTTPException(status_code=403, detail="superadmin_required")
    return claims


def ensure_tenant_scope_claims(claims: dict[str, Any], *, request: Request | None = None) -> str:
    if request is not None and _request_authz_cache_enabled():
        cache = _request_authz_cache_get(request)
        cached_sig = cache.get("tenant_scope_claims_signature")
        cached_tenant_id = cache.get("tenant_scope_tenant_id")
        if isinstance(cached_sig, tuple) and isinstance(cached_tenant_id, str):
            if cached_sig == _claims_signature(claims):
                return cached_tenant_id

    tenant_id = str(claims.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="missing_tenant_context")

    _require_superadmin_support_scope(claims, tenant_id=tenant_id)
    if request is not None and _request_authz_cache_enabled():
        cache = _request_authz_cache_get(request)
        cache["tenant_scope_claims_signature"] = _claims_signature(claims)
        cache["tenant_scope_tenant_id"] = tenant_id
    return tenant_id


def require_tenant_context(
    request: Request,
    claims: dict[str, Any] = Depends(require_claims),
) -> dict[str, Any]:
    ensure_tenant_scope_claims(claims, request=request)
    return claims


def require_tenant_admin(claims: dict[str, Any] = Depends(require_tenant_context)) -> dict[str, Any]:
    roles = set(claims.get("roles") or [])
    if not ({"TENANT_ADMIN", "SUPERADMIN"} & roles):
        raise HTTPException(status_code=403, detail="tenant_admin_required")
    return claims


def enforce_permissions(claims: dict[str, Any], required: list[str] | tuple[str, ...], *, any_of: bool = False) -> list[str]:
    policy_started = time.perf_counter()
    wanted = [normalize_permission(x) for x in list(required or []) if normalize_permission(x)]
    if not wanted:
        raise HTTPException(status_code=500, detail="permission_policy_invalid")

    try:
        effective = effective_permissions_from_claims(claims)
        allowed = any(is_permission_allowed(code, effective) for code in wanted) if any_of else all(is_permission_allowed(code, effective) for code in wanted)
        if not allowed:
            raise HTTPException(status_code=403, detail="permission_required:" + ",".join(wanted))
        return effective
    finally:
        if _protected_envelope_breakdown_enabled():
            record_segment("protected_policy_ms", (time.perf_counter() - policy_started) * 1000.0)


def enforce_permission(claims: dict[str, Any], permission_code: str) -> list[str]:
    return enforce_permissions(claims, [permission_code], any_of=False)


def require_claim_permission(permission_code: str):
    def _dep(claims: dict[str, Any] = Depends(require_claims)) -> dict[str, Any]:
        enforce_permission(claims, permission_code)
        return claims

    return _dep


def require_tenant_admin_permission(permission_code: str):
    def _dep(claims: dict[str, Any] = Depends(require_tenant_admin)) -> dict[str, Any]:
        enforce_permission(claims, permission_code)
        return claims

    return _dep


def require_superadmin_permission(permission_code: str):
    def _dep(claims: dict[str, Any] = Depends(require_superadmin)) -> dict[str, Any]:
        enforce_permission(claims, permission_code)
        return claims

    return _dep
