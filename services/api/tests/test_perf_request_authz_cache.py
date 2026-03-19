from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import app.core.auth as core_auth
import app.core.middleware as core_middleware
import app.core.policy_matrix as policy_matrix
from app.core.auth import create_access_token


@dataclass
class _FakeQuery:
    _row: object

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._row


@dataclass
class _FakeDB:
    _row: object

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._row)

    def close(self):
        return None


def _claims(*, tenant_id: str = "tenant-dev-001", roles: list[str] | None = None) -> dict[str, object]:
    return {
        "sub": "user@tenant.local",
        "tenant_id": tenant_id,
        "roles": list(roles or ["USER"]),
        "iss": "mydata",
        "aud": "mydata-api",
        "exp": 4102444800,
    }


def _build_policy_probe_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(core_middleware.AuthContextMiddleware)

    router = APIRouter(dependencies=[Depends(policy_matrix.enforce_request_policy)])

    @router.get("/orders")
    def _orders_probe(claims: dict[str, object] = Depends(core_auth.require_tenant_context)) -> dict[str, str]:
        return {"tenant_id": str(claims.get("tenant_id") or "")}

    app.include_router(router)
    return app


def test_request_authz_cache_reuses_tenant_db_permissions_in_single_request(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", raising=False)
    monkeypatch.setenv("AUTHZ_TENANT_DB_FAST_PATH_ENABLED", "0")
    monkeypatch.setenv("AUTHZ_TENANT_DB_FAST_PATH_SHADOW_COMPARE_ENABLED", "0")
    policy_matrix.get_settings.cache_clear()

    canonical_calls: list[tuple[str, str]] = []

    def _canonical(*, db, tenant_id: str, user_id: str) -> list[str]:  # noqa: ARG001
        canonical_calls.append((tenant_id, user_id))
        return ["ORDERS.READ"]

    monkeypatch.setattr(policy_matrix, "_tenant_db_effective_permissions_from_canonical", _canonical)
    monkeypatch.setattr(policy_matrix, "get_session_factory", lambda: (lambda: _FakeDB(object())))

    request = SimpleNamespace(state=SimpleNamespace())
    claims = _claims(tenant_id="tenant-cache-1", roles=["USER"])

    try:
        first = policy_matrix._tenant_db_effective_permissions(claims=claims, request=request)
        second = policy_matrix._tenant_db_effective_permissions(claims=claims, request=request)
    finally:
        policy_matrix.get_settings.cache_clear()

    assert first == ["ORDERS.READ"]
    assert second == ["ORDERS.READ"]
    assert canonical_calls == [("tenant-cache-1", "user@tenant.local")]


def test_request_authz_cache_reuses_tenant_scope_validation_in_single_request(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", raising=False)

    scope_checks: list[str] = []

    def _support_scope(*_args, tenant_id: str, **_kwargs) -> None:
        scope_checks.append(tenant_id)

    monkeypatch.setattr(core_auth, "_require_superadmin_support_scope", _support_scope)

    token = create_access_token(
        {
            "sub": "sa@platform.local",
            "roles": ["SUPERADMIN"],
            "tenant_id": "tenant-a",
            "support_tenant_id": "tenant-a",
            "support_session_id": "sess-1",
        }
    )

    client = TestClient(_build_policy_probe_app())
    r = client.get("/orders", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert (r.json() or {}).get("tenant_id") == "tenant-a"
    assert scope_checks == ["tenant-a"]


def test_request_authz_cache_can_be_disabled_for_legacy_path(monkeypatch) -> None:
    monkeypatch.setenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", "0")

    scope_checks: list[str] = []

    def _support_scope(*_args, tenant_id: str, **_kwargs) -> None:
        scope_checks.append(tenant_id)

    monkeypatch.setattr(core_auth, "_require_superadmin_support_scope", _support_scope)

    token = create_access_token(
        {
            "sub": "sa@platform.local",
            "roles": ["SUPERADMIN"],
            "tenant_id": "tenant-legacy",
            "support_tenant_id": "tenant-legacy",
            "support_session_id": "sess-legacy",
        }
    )

    client = TestClient(_build_policy_probe_app())
    r = client.get("/orders", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert scope_checks == ["tenant-legacy", "tenant-legacy"]


def test_request_authz_cache_has_no_cross_request_leakage(monkeypatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_REQUEST_AUTHZ_CACHE", raising=False)

    scope_checks: list[str] = []

    def _support_scope(*_args, tenant_id: str, **_kwargs) -> None:
        scope_checks.append(tenant_id)

    monkeypatch.setattr(core_auth, "_require_superadmin_support_scope", _support_scope)

    token_a = create_access_token(
        {
            "sub": "sa@platform.local",
            "roles": ["SUPERADMIN"],
            "tenant_id": "tenant-a",
            "support_tenant_id": "tenant-a",
            "support_session_id": "sess-a",
        }
    )
    token_b = create_access_token(
        {
            "sub": "sa@platform.local",
            "roles": ["SUPERADMIN"],
            "tenant_id": "tenant-b",
            "support_tenant_id": "tenant-b",
            "support_session_id": "sess-b",
        }
    )

    client = TestClient(_build_policy_probe_app())
    ra = client.get("/orders", headers={"Authorization": f"Bearer {token_a}"})
    rb = client.get("/orders", headers={"Authorization": f"Bearer {token_b}"})

    assert ra.status_code == 200
    assert rb.status_code == 200
    assert (ra.json() or {}).get("tenant_id") == "tenant-a"
    assert (rb.json() or {}).get("tenant_id") == "tenant-b"
    assert scope_checks == ["tenant-a", "tenant-b"]
