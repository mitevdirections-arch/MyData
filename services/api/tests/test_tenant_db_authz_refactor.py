from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.core.policy_matrix as pm
from app.core.auth import create_access_token, require_claims
from app.core.permissions import dedupe_permissions

@pytest.fixture(autouse=True)
def _reset_fast_path_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        pm,
        "get_settings",
        lambda: SimpleNamespace(
            authz_tenant_db_fast_path_enabled=False,
            authz_tenant_db_fast_path_shadow_compare_enabled=False,
            authz_tenant_db_fast_path_source_version=1,
            guard_device_policy_enabled=True,
            guard_device_header_name="X-Device-ID",
        ),
    )


class _FakeQuery:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def outerjoin(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        if self._db.raise_on_all:
            raise RuntimeError("db_down")
        return list(self._db.rows)


class _FakeExecuteResult:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def all(self):
        if self._db.raise_on_all:
            raise RuntimeError("db_down")
        return list(self._db.rows)


class _FakeDB:
    def __init__(self, *, rows: list[tuple[str, list[str], list[str] | None]], raise_on_all: bool = False) -> None:
        self.rows = list(rows)
        self.raise_on_all = bool(raise_on_all)
        self.query_calls = 0
        self.closed = False

    def query(self, *_args, **_kwargs):
        self.query_calls += 1
        return _FakeQuery(self)

    def execute(self, *_args, **_kwargs):
        self.query_calls += 1
        return _FakeExecuteResult(self)

    def close(self) -> None:
        self.closed = True


def _claims(*, sub: str = "user@tenant.local", tenant_id: str = "tenant-x", roles: list[str] | None = None) -> dict[str, object]:
    return {
        "sub": sub,
        "tenant_id": tenant_id,
        "roles": list(roles or ["TENANT_ADMIN"]),
    }


def _make_request(
    *,
    method: str = "GET",
    path: str = "/orders",
    claims: dict[str, object] | None = None,
    device_id: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if device_id:
        headers.append((b"x-device-id", str(device_id).encode("utf-8")))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 9999),
        "server": ("test", 80),
        "route": SimpleNamespace(path=path),
    }
    req = Request(scope)
    req.state.claims = dict(claims or _claims())
    return req


def _legacy_effective_permissions(*, direct_permissions: list[str], role_codes: list[str], role_perms_by_code: dict[str, list[str]]) -> list[str]:
    role_permissions: list[str] = []
    for code in role_codes:
        role_permissions.extend(list(role_perms_by_code.get(code, [])))
    return dedupe_permissions([*list(direct_permissions or []), *role_permissions])


def test_tenant_db_authz_single_query_and_equivalent_merge(monkeypatch) -> None:
    direct_permissions = ["orders.read", "ORDERS.READ", "PROFILE.READ"]
    role_codes = ["DISPATCHER", "IT_ADMIN"]
    role_perms_by_code = {
        "DISPATCHER": ["ORDERS.READ", "ORDERS.WRITE"],
        "IT_ADMIN": ["IAM.READ", "IAM.WRITE"],
    }

    rows = [("ACTIVE", direct_permissions, role_perms_by_code[code]) for code in role_codes]
    fake_db = _FakeDB(rows=rows)
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: fake_db))

    out = pm._tenant_db_effective_permissions(claims=_claims())
    expected = _legacy_effective_permissions(
        direct_permissions=direct_permissions,
        role_codes=role_codes,
        role_perms_by_code=role_perms_by_code,
    )

    assert set(out) == set(expected)
    assert fake_db.query_calls == 1
    assert fake_db.closed is True


def test_tenant_db_authz_missing_binding_denies(monkeypatch) -> None:
    fake_db = _FakeDB(rows=[])
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: fake_db))

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == []
    assert fake_db.query_calls == 1
    assert fake_db.closed is True


def test_tenant_db_authz_inactive_employment_denies(monkeypatch) -> None:
    fake_db = _FakeDB(rows=[("INACTIVE", ["ORDERS.READ"], ["ORDERS.WRITE"])])
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: fake_db))

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == []
    assert fake_db.query_calls == 1
    assert fake_db.closed is True


def test_tenant_db_authz_db_error_fail_closed(monkeypatch) -> None:
    fake_db = _FakeDB(rows=[("ACTIVE", ["ORDERS.READ"], ["ORDERS.WRITE"])], raise_on_all=True)
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: fake_db))

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == []
    assert fake_db.query_calls == 1
    assert fake_db.closed is True


def test_tenant_db_authz_superadmin_bypass_without_db(monkeypatch) -> None:
    fake_db = _FakeDB(rows=[])
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: fake_db))
    monkeypatch.setattr(pm, "ensure_tenant_scope_claims", lambda _claims: "tenant-x")

    out = pm._tenant_db_effective_permissions(claims=_claims(roles=["SUPERADMIN"], tenant_id="tenant-x"))

    assert out == ["*"]
    assert fake_db.query_calls == 0


def test_require_claims_forged_tenant_context_denied() -> None:
    token = create_access_token({"sub": "user@tenant.local", "tenant_id": "tenant-a", "roles": ["TENANT_ADMIN"]})
    request = _make_request(path="/orders", claims=None)

    with pytest.raises(HTTPException) as exc:
        require_claims(request=request, authorization=f"Bearer {token}", x_tenant_id="tenant-b")

    assert int(exc.value.status_code) == 403
    assert str(exc.value.detail) == "tenant_context_mismatch"


def test_invalid_authz_source_is_fail_closed() -> None:
    rule = pm.RoutePolicy(permission_code="ORDERS.READ", authz_source="BROKEN_SOURCE")

    with pytest.raises(HTTPException) as exc:
        pm._effective_permissions_for_rule(claims=_claims(), rule=rule)

    assert int(exc.value.status_code) == 403
    assert str(exc.value.detail) == "policy_authz_source_invalid"


def test_orders_policy_enforces_permission_from_tenant_db(monkeypatch) -> None:
    request = _make_request(path="/orders", claims=_claims())

    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: [])
    with pytest.raises(HTTPException) as deny_exc:
        pm.enforce_request_policy(request)
    assert int(deny_exc.value.status_code) == 403
    assert str(deny_exc.value.detail).startswith("permission_required:ORDERS.READ")

    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: ["ORDERS.READ"])
    monkeypatch.setattr(pm, "_enforce_device_policy_for_business_routes", lambda **_kwargs: None)
    pm.enforce_request_policy(request)


def test_orders_policy_requires_device_context_when_permission_allows(monkeypatch) -> None:
    request = _make_request(path="/orders", claims=_claims())
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions", lambda *, claims: ["ORDERS.READ"])
    with pytest.raises(HTTPException) as exc:
        pm.enforce_request_policy(request)
    assert int(exc.value.status_code) == 403
    assert str(exc.value.detail) == "DEVICE_CONTEXT_REQUIRED"

class _CloseOnlyDB:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _configure_fast_path_settings(monkeypatch, *, enabled: bool, shadow: bool, source_version: int = 1):
    monkeypatch.setattr(
        pm,
        "get_settings",
        lambda: SimpleNamespace(
            authz_tenant_db_fast_path_enabled=bool(enabled),
            authz_tenant_db_fast_path_shadow_compare_enabled=bool(shadow),
            authz_tenant_db_fast_path_source_version=int(source_version),
        ),
    )


def test_tenant_db_authz_fast_path_valid_row_is_used_when_enabled(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=True, shadow=False, source_version=7)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))

    captured: dict[str, object] = {}

    def _fast(**kwargs):
        captured.update(kwargs)
        return ["ORDERS.READ"], True

    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", _fast)
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.WRITE"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.READ"]
    assert db.closed is True
    assert captured.get("required_source_version") == 7


def test_tenant_db_authz_fast_path_missing_or_invalid_row_falls_back_to_legacy(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=True, shadow=False, source_version=3)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", lambda **_kwargs: (None, False))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.READ"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.READ"]
    assert db.closed is True


def test_tenant_db_authz_fast_path_shadow_mismatch_falls_back_to_legacy(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=True, shadow=True, source_version=1)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", lambda **_kwargs: (["ORDERS.READ"], True))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.WRITE"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.WRITE"]
    assert db.closed is True


def test_tenant_db_authz_shadow_mode_mismatch_keeps_legacy_decision(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=False, shadow=True, source_version=1)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", lambda **_kwargs: (["ORDERS.READ"], True))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.WRITE"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.WRITE"]
    assert db.closed is True


def test_tenant_db_authz_shadow_mode_ignores_missing_fast_row_in_legacy_mode(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=False, shadow=True, source_version=1)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", lambda **_kwargs: (None, False))
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.READ"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.READ"]
    assert db.closed is True


def test_tenant_db_authz_fast_path_exception_falls_back_to_legacy(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=True, shadow=False, source_version=1)

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))

    def _fast(**_kwargs):
        raise RuntimeError("fast_path_unavailable")

    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", _fast)
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", lambda **_kwargs: ["ORDERS.READ"])

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.READ"]
    assert db.closed is True


def test_tenant_db_authz_fast_path_env_overrides_settings(monkeypatch) -> None:
    _configure_fast_path_settings(monkeypatch, enabled=False, shadow=False, source_version=1)
    monkeypatch.setenv("MYDATA_AUTHZ_FAST_PATH_ENABLED", "1")
    monkeypatch.setenv("MYDATA_AUTHZ_FAST_PATH_SHADOW", "1")

    db = _CloseOnlyDB()
    monkeypatch.setattr(pm, "get_session_factory", lambda: (lambda: db))

    calls: dict[str, int] = {"fast": 0, "canonical": 0}

    def _fast(**_kwargs):
        calls["fast"] += 1
        return ["ORDERS.READ"], True

    def _canonical(**_kwargs):
        calls["canonical"] += 1
        return ["ORDERS.READ"]

    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_fast_path", _fast)
    monkeypatch.setattr(pm, "_tenant_db_effective_permissions_from_canonical", _canonical)

    out = pm._tenant_db_effective_permissions(claims=_claims())

    assert out == ["ORDERS.READ"]
    assert calls["fast"] == 1
    assert calls["canonical"] == 1
    assert db.closed is True

