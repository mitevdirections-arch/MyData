from fastapi.testclient import TestClient

from app.core.auth import create_access_token, get_settings
from app.core.policy_matrix import (
    AUTHZ_MODE_DB_TRUTH,
    AUTHZ_MODE_FAST_PATH,
    AUTHZ_MODE_TOKEN_CLAIMS,
    AUTHZ_SOURCE_TENANT_DB,
    ROUTE_POLICY,
    is_protected_route_path,
    protected_routes_without_explicit_authz_mode,
)
from app.main import app


def _token(*, sub: str, roles: list[str], tenant_id: str) -> str:
    return create_access_token({"sub": sub, "roles": roles, "tenant_id": tenant_id})


def test_policy_matrix_covers_all_protected_routes() -> None:
    missing: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if not path:
            continue
        if "HEAD" in methods and "GET" in methods:
            methods.remove("HEAD")
        for method in sorted(methods):
            if not is_protected_route_path(path):
                continue
            if (method, path) not in ROUTE_POLICY:
                missing.append(f"{method} {path}")

    assert missing == []


def test_all_protected_routes_have_explicit_authz_mode_contract() -> None:
    allowed_modes = {AUTHZ_MODE_DB_TRUTH, AUTHZ_MODE_TOKEN_CLAIMS, AUTHZ_MODE_FAST_PATH}

    missing_or_invalid: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if not path:
            continue
        if "HEAD" in methods and "GET" in methods:
            methods.remove("HEAD")
        for method in sorted(methods):
            if not is_protected_route_path(path):
                continue
            rule = ROUTE_POLICY.get((method, path))
            if rule is None:
                missing_or_invalid.append(f"{method} {path}:missing_policy")
                continue
            mode = str(rule.authz_mode or "").strip().upper()
            if mode not in allowed_modes:
                missing_or_invalid.append(f"{method} {path}:invalid_authz_mode:{mode or 'EMPTY'}")

    assert missing_or_invalid == []
    assert protected_routes_without_explicit_authz_mode() == []


def test_orders_policy_uses_tenant_db_authz_contract() -> None:
    for key in [("GET", "/orders"), ("POST", "/orders"), ("GET", "/orders/{order_id}")]:
        rule = ROUTE_POLICY.get(key)
        assert rule is not None
        assert str(rule.authz_source or "").upper() == AUTHZ_SOURCE_TENANT_DB
        assert str(rule.authz_mode or "").upper() == AUTHZ_MODE_DB_TRUTH


def test_policy_permission_denied_without_required_permission() -> None:
    client = TestClient(app)
    tok = _token(sub="user@tenant.local", roles=["USER"], tenant_id="tenant-dev-001")
    r = client.get("/iam/admin/rls-context", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert str((r.json() or {}).get("detail") or "").startswith("permission_required:IAM.READ")


def test_policy_fail_closed_when_rule_missing() -> None:
    client = TestClient(app)
    tok = _token(sub="sa@platform.local", roles=["SUPERADMIN"], tenant_id="platform")

    key = ("GET", "/iam/admin/rls-context")
    old = ROUTE_POLICY.pop(key)
    try:
        r = client.get("/iam/admin/rls-context", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403
        assert (r.json() or {}).get("detail") == "policy_missing_for_route"
    finally:
        ROUTE_POLICY[key] = old


def test_step_up_required_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SUPERADMIN_STEP_UP_ENABLED", "true")
    monkeypatch.setenv("SUPERADMIN_STEP_UP_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        tok = _token(sub="sa@platform.local", roles=["SUPERADMIN"], tenant_id="platform")
        r = client.post(
            "/admin/tenants/bootstrap-demo",
            headers={"Authorization": f"Bearer {tok}"},
            json={"tenant_id": "tenant-pol-001", "name": "Tenant Pol"},
        )
        assert r.status_code == 403
        assert (r.json() or {}).get("detail") == "step_up_required"
    finally:
        get_settings.cache_clear()
