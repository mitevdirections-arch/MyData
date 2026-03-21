from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app
from app.modules.profile.router_parts import admin_user_domain as profile_admin_user_domain
from app.modules.profile.router_parts import admin_workspace as profile_admin_workspace
from app.modules.users.router_parts import admin_user_domain as users_admin_user_domain
from app.modules.users.router_parts import admin_workspace as users_admin_workspace
from app.modules.users.service import service as users_service


class _DummyDB:
    pass


def _route(path: str, method: str) -> APIRoute:
    wanted = method.upper()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and wanted in route.methods:
            return route
    raise AssertionError(f"route_not_found:{method}:{path}")


def test_users_surface_routes_are_bound_to_users_router_parts() -> None:
    route_users = _route("/users/admin/users", "GET")
    route_provision = _route("/users/admin/users/{user_id}/provision", "POST")
    route_contacts = _route("/users/admin/users/{user_id}/contacts", "GET")
    route_self = _route("/users/me", "GET")
    route_self_pw = _route("/users/me/credentials/change-password", "POST")
    route_self_username = _route("/users/me/credentials/change-username", "POST")

    assert route_users.endpoint.__module__ == "app.modules.users.router_parts.admin_workspace"
    assert route_provision.endpoint.__module__ == "app.modules.users.router_parts.admin_workspace"
    assert route_contacts.endpoint.__module__ == "app.modules.users.router_parts.admin_user_domain"
    assert route_self.endpoint.__module__ == "app.modules.users.router_parts.self_profile"
    assert route_self_pw.endpoint.__module__ == "app.modules.users.router_parts.self_credentials"
    assert route_self_username.endpoint.__module__ == "app.modules.users.router_parts.self_credentials"


def test_profile_self_credential_routes_use_users_canonical_handlers() -> None:
    route_profile_pw = _route("/profile/me/credentials/change-password", "POST")
    route_profile_username = _route("/profile/me/credentials/change-username", "POST")
    assert route_profile_pw.endpoint.__module__ == "app.modules.users.router_parts.self_credentials"
    assert route_profile_username.endpoint.__module__ == "app.modules.users.router_parts.self_credentials"


def test_profile_and_users_admin_users_call_canonical_users_service(monkeypatch) -> None:
    calls: list[tuple[str, str, str, int]] = []

    def _spy_list_workspace_users(db, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 200):
        calls.append((workspace_type, workspace_id, actor, int(limit)))
        return []

    monkeypatch.setattr(users_service, "list_workspace_users", _spy_list_workspace_users)

    out_profile = profile_admin_workspace.list_users(
        workspace=None,
        limit=25,
        claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-test", "sub": "admin@tenant.test"},
        db=_DummyDB(),
    )
    out_users = users_admin_workspace.list_users(
        workspace=None,
        limit=30,
        claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-test", "sub": "admin@tenant.test"},
        db=_DummyDB(),
    )

    assert out_profile["ok"] is True
    assert out_users["ok"] is True
    assert calls == [
        ("TENANT", "tenant-test", "admin@tenant.test", 25),
        ("TENANT", "tenant-test", "admin@tenant.test", 30),
    ]


def test_profile_and_users_admin_user_contacts_call_canonical_users_service(monkeypatch) -> None:
    calls: list[tuple[str, str, str, str, int]] = []

    def _spy_list_user_contacts(db, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, limit: int = 500):
        calls.append((workspace_type, workspace_id, user_id, actor, int(limit)))
        return []

    monkeypatch.setattr(users_service, "list_user_contacts", _spy_list_user_contacts)

    out_profile = profile_admin_user_domain.list_user_contacts(
        user_id="worker-1",
        workspace=None,
        limit=10,
        claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-test", "sub": "admin@tenant.test"},
        db=_DummyDB(),
    )
    out_users = users_admin_user_domain.list_user_contacts(
        user_id="worker-1",
        workspace=None,
        limit=12,
        claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-test", "sub": "admin@tenant.test"},
        db=_DummyDB(),
    )

    assert out_profile["ok"] is True
    assert out_users["ok"] is True
    assert calls == [
        ("TENANT", "tenant-test", "worker-1", "admin@tenant.test", 10),
        ("TENANT", "tenant-test", "worker-1", "admin@tenant.test", 12),
    ]
