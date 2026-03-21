from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from fastapi.routing import APIRoute
from fastapi import HTTPException
import pytest

from app.main import app
from app.modules.users.router_parts import admin_workspace as users_admin_workspace
from app.modules.users.service import service as users_service


class _FakeQuery:
    def __init__(self, *, first_row=None, scalar_value=None) -> None:
        self._first_row = first_row
        self._scalar_value = scalar_value

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._first_row

    def scalar(self):
        return self._scalar_value


class _FakeRoleDeleteDB:
    def __init__(self, *, role_row, assignment_count: int) -> None:
        self._role_row = role_row
        self._assignment_count = int(assignment_count)
        self.deleted = None

    def query(self, entity):
        if "count(" in str(entity).lower():
            return _FakeQuery(scalar_value=self._assignment_count)
        return _FakeQuery(first_row=self._role_row)

    def delete(self, row) -> None:
        self.deleted = row

    def flush(self) -> None:
        return None


class _FakeUserLookupDB:
    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(first_row=None)


class _DummyDB:
    pass


def _methods_for(path: str) -> set[str]:
    out: set[str] = set()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path:
            out.update(set(route.methods or set()))
    if out:
        return out
    raise AssertionError(f"route_not_found:{path}")


def test_role_route_supports_delete_for_users_and_profile_surfaces() -> None:
    users_methods = _methods_for("/users/admin/roles/{role_code}")
    profile_methods = _methods_for("/profile/admin/roles/{role_code}")

    assert {"PUT", "DELETE"}.issubset(users_methods)
    assert {"PUT", "DELETE"}.issubset(profile_methods)


def test_users_service_set_workspace_user_roles_requires_existing_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_service, "_ensure_default_roles", lambda *_args, **_kwargs: None)
    db = _FakeUserLookupDB()

    with pytest.raises(ValueError, match="user_membership_required"):
        users_service.set_workspace_user_roles(
            db,
            workspace_type="TENANT",
            workspace_id="tenant-hardening",
            user_id="missing@tenant.local",
            role_codes=["TENANT_ADMIN"],
            actor="admin@tenant.local",
        )


def test_users_service_delete_role_denies_when_assigned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_service, "_ensure_default_roles", lambda *_args, **_kwargs: None)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_type="TENANT",
        workspace_id="tenant-hardening",
        role_code="DISPATCHER",
        role_name="Dispatcher",
        description="Dispatcher role",
        permissions_json=["ORDERS.READ"],
        is_system=False,
        updated_by="seed",
        updated_at=datetime.now(timezone.utc),
    )
    db = _FakeRoleDeleteDB(role_row=row, assignment_count=2)

    with pytest.raises(ValueError, match="role_in_use"):
        users_service.delete_role(
            db,
            workspace_type="TENANT",
            workspace_id="tenant-hardening",
            role_code="DISPATCHER",
            actor="admin@tenant.local",
        )
    assert db.deleted is None


def test_users_service_delete_role_succeeds_when_unassigned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_service, "_ensure_default_roles", lambda *_args, **_kwargs: None)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_type="TENANT",
        workspace_id="tenant-hardening",
        role_code="CUSTOM_ROLE",
        role_name="Custom Role",
        description="Custom role",
        permissions_json=["IAM.READ"],
        is_system=False,
        updated_by="seed",
        updated_at=datetime.now(timezone.utc),
    )
    db = _FakeRoleDeleteDB(role_row=row, assignment_count=0)

    out = users_service.delete_role(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-hardening",
        role_code="CUSTOM_ROLE",
        actor="admin@tenant.local",
    )
    assert out["role_code"] == "CUSTOM_ROLE"
    assert db.deleted is row


def test_users_admin_delete_role_maps_role_in_use_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ValueError("role_in_use")

    monkeypatch.setattr(users_service, "delete_role", _raise)

    with pytest.raises(HTTPException) as exc:
        users_admin_workspace.delete_role(
            role_code="CUSTOM_ROLE",
            workspace=None,
            claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-hardening", "sub": "admin@tenant.local"},
            db=_DummyDB(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "role_in_use"
