from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.db.session import get_db_session
from app.main import app
import app.modules.guard.router as guard_router


class _FakeDB:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _auth_headers(*, tenant_id: str = "platform", sub: str = "superadmin@ops.local") -> dict[str, str]:
    tok = create_access_token({"sub": sub, "roles": ["SUPERADMIN"], "tenant_id": tenant_id})
    return {"Authorization": f"Bearer {tok}"}


def test_guard_device_policy_openapi_paths_exist() -> None:
    schema = app.openapi()
    paths = schema.get("paths") or {}
    assert "/guard/device/status" in paths
    assert "/guard/device/activate" in paths
    assert "/guard/device/logout" in paths
    assert "get" in paths["/guard/device/status"]
    assert "post" in paths["/guard/device/activate"]
    assert "post" in paths["/guard/device/logout"]


def test_guard_device_policy_routes_contract(monkeypatch) -> None:
    app.dependency_overrides[get_db_session] = lambda: _FakeDB()
    headers = _auth_headers()
    monkeypatch.setattr(guard_router, "write_audit", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        guard_router.service,
        "get_device_status",
        lambda db, *, tenant_id, user_id, device_id: {  # noqa: ARG005
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": {"device_id": device_id, "state": "BACKGROUND_REACHABLE"},
            "active_device": {"device_id": "desktop-1", "state": "ACTIVE"},
        },
    )
    monkeypatch.setattr(
        guard_router.service,
        "activate_device",
        lambda db, *, tenant_id, user_id, device_id, actor: {  # noqa: ARG005
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": {"device_id": device_id, "state": "ACTIVE"},
            "non_blocking": True,
        },
    )
    monkeypatch.setattr(
        guard_router.service,
        "logout_device",
        lambda db, *, tenant_id, user_id, device_id, actor: {  # noqa: ARG005
            "ok": True,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "device": {"device_id": device_id, "state": "LOGGED_OUT"},
            "next_active_candidate": None,
            "non_blocking": True,
        },
    )

    try:
        client = TestClient(app)
        status_resp = client.get("/guard/device/status", headers={**headers, "X-Device-ID": "mobile-1"})
        assert status_resp.status_code == 200
        assert (status_resp.json() or {}).get("device", {}).get("state") == "BACKGROUND_REACHABLE"

        activate_resp = client.post(
            "/guard/device/activate",
            headers={**headers, "X-Device-ID": "mobile-1"},
            json={"device_id": "mobile-1"},
        )
        assert activate_resp.status_code == 200
        assert (activate_resp.json() or {}).get("device", {}).get("state") == "ACTIVE"

        logout_resp = client.post(
            "/guard/device/logout",
            headers={**headers, "X-Device-ID": "mobile-1"},
            json={"device_id": "mobile-1"},
        )
        assert logout_resp.status_code == 200
        assert (logout_resp.json() or {}).get("device", {}).get("state") == "LOGGED_OUT"
    finally:
        app.dependency_overrides.clear()
