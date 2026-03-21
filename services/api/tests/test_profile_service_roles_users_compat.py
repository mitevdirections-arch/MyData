from __future__ import annotations

from app.modules.profile.service import service as profile_service
from app.modules.users.service import service as users_service


class _DummyDB:
    pass


def test_profile_service_role_user_methods_delegate_to_canonical_users_service(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def _spy_list_roles(db, *, workspace_type: str, workspace_id: str, actor: str, limit: int = 500):
        calls.append(("list_roles", workspace_type, workspace_id))
        return [{"role_code": "TENANT_ADMIN"}]

    def _spy_set_roles(db, *, workspace_type: str, workspace_id: str, user_id: str, role_codes, actor: str):
        calls.append(("set_workspace_user_roles", workspace_type, workspace_id))
        return {"user_id": user_id, "roles": list(role_codes or [])}

    monkeypatch.setattr(users_service, "list_roles", _spy_list_roles)
    monkeypatch.setattr(users_service, "set_workspace_user_roles", _spy_set_roles)

    roles_out = profile_service.list_roles(
        _DummyDB(),
        workspace_type="TENANT",
        workspace_id="tenant-compat",
        actor="admin@tenant.local",
        limit=10,
    )
    assign_out = profile_service.set_workspace_user_roles(
        _DummyDB(),
        workspace_type="TENANT",
        workspace_id="tenant-compat",
        user_id="worker@tenant.local",
        role_codes=["DISPATCHER"],
        actor="admin@tenant.local",
    )

    assert roles_out == [{"role_code": "TENANT_ADMIN"}]
    assert assign_out["roles"] == ["DISPATCHER"]
    assert calls == [
        ("list_roles", "TENANT", "tenant-compat"),
        ("set_workspace_user_roles", "TENANT", "tenant-compat"),
    ]
