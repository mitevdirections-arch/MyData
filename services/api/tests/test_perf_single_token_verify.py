from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

import app.core.middleware as core_middleware


class _TamperVerifiedContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if str(request.url.path or "").startswith("/ai/tenant-copilot/"):
            setattr(request.state, core_middleware._AUTH_CONTEXT_TOKEN_FP_ATTR, "tampered")
        return await call_next(request)


def _build_probe_app(*, tamper_verified_context: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(core_middleware.AuthContextMiddleware)
    if tamper_verified_context:
        app.add_middleware(_TamperVerifiedContextMiddleware)
    app.add_middleware(core_middleware.CoreEntitlementMiddleware)

    @app.get("/ai/tenant-copilot/probe")
    def protected_probe(request: Request) -> dict[str, bool]:
        claims = getattr(request.state, "claims", None)
        return {"claims_present": isinstance(claims, dict)}

    return app


def _superadmin_claims() -> dict[str, object]:
    return {
        "sub": "sa@platform.local",
        "roles": ["SUPERADMIN"],
        "tenant_id": "platform",
        "iss": "mydata",
        "aud": "mydata-api",
        "exp": 4102444800,
    }


def test_single_verify_on_protected_request_default_enabled(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_SINGLE_VERIFY", raising=False)

    calls: list[str] = []

    def _verify(token: str) -> dict[str, object]:
        calls.append(token)
        return _superadmin_claims()

    monkeypatch.setattr(core_middleware, "verify_access_token", _verify)

    client = TestClient(_build_probe_app())
    r = client.get("/ai/tenant-copilot/probe", headers={"Authorization": "Bearer token-1"})

    assert r.status_code == 200
    assert (r.json() or {}).get("claims_present") is True
    assert calls == ["token-1"]


def test_legacy_path_duplicate_verify_when_switch_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MYDATA_PERF_SINGLE_VERIFY", "0")

    calls: list[str] = []

    def _verify(token: str) -> dict[str, object]:
        calls.append(token)
        return _superadmin_claims()

    monkeypatch.setattr(core_middleware, "verify_access_token", _verify)

    client = TestClient(_build_probe_app())
    r = client.get("/ai/tenant-copilot/probe", headers={"Authorization": "Bearer token-2"})

    assert r.status_code == 200
    assert (r.json() or {}).get("claims_present") is True
    assert calls == ["token-2", "token-2"]


def test_fail_closed_behavior_preserved_for_invalid_token(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_SINGLE_VERIFY", raising=False)

    calls: list[str] = []

    def _verify(token: str) -> dict[str, object]:
        calls.append(token)
        raise Exception("invalid_token_signature")

    monkeypatch.setattr(core_middleware, "verify_access_token", _verify)

    client = TestClient(_build_probe_app())
    r = client.get("/ai/tenant-copilot/probe", headers={"Authorization": "Bearer bad-token"})

    assert r.status_code == 401
    assert (r.json() or {}).get("detail") == "invalid_token_signature"
    assert calls == ["bad-token"]


def test_fallback_verify_when_shared_context_is_incompatible(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_SINGLE_VERIFY", raising=False)

    calls: list[str] = []

    def _verify(token: str) -> dict[str, object]:
        calls.append(token)
        return _superadmin_claims()

    monkeypatch.setattr(core_middleware, "verify_access_token", _verify)

    client = TestClient(_build_probe_app(tamper_verified_context=True))
    r = client.get("/ai/tenant-copilot/probe", headers={"Authorization": "Bearer token-3"})

    assert r.status_code == 200
    assert (r.json() or {}).get("claims_present") is True
    assert calls == ["token-3", "token-3"]