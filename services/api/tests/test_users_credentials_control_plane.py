from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app.db.models import WorkspaceUser, WorkspaceUserCredential
from app.modules.profile.router_parts import admin_workspace as profile_admin_workspace
from app.modules.profile.router_parts import admin_user_domain as profile_admin_user_domain
from app.modules.users.router_parts import admin_workspace as users_admin_workspace
from app.modules.users.router_parts import admin_user_domain as users_admin_user_domain
from app.modules.users.service import service as users_service


class _FakeQuery:
    def __init__(self, *, first_row=None) -> None:
        self._first_row = first_row

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._first_row


class _FakeCredentialDB:
    def __init__(self, *, user_row=None, credential_row=None) -> None:
        self.user_row = user_row
        self.credential_row = credential_row
        self.added: list[object] = []

    def query(self, entity):
        if entity is WorkspaceUser:
            return _FakeQuery(first_row=self.user_row)
        if entity is WorkspaceUserCredential:
            return _FakeQuery(first_row=self.credential_row)
        return _FakeQuery(first_row=None)

    def add(self, row) -> None:
        self.added.append(row)
        if isinstance(row, WorkspaceUserCredential):
            self.credential_row = row

    def flush(self) -> None:
        return None


class _DummyDB:
    def commit(self) -> None:
        return None


def test_issue_credentials_requires_existing_membership_no_auto_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users_service, "_ensure_workspace_exists", lambda *_args, **_kwargs: None)
    db = _FakeCredentialDB(user_row=None, credential_row=None)

    with pytest.raises(ValueError, match="user_membership_required"):
        users_service.issue_user_credentials(
            db,
            workspace_type="TENANT",
            workspace_id="tenant-cred-01",
            user_id="missing@tenant.local",
            actor="admin@tenant.local",
            payload={},
            reset_existing=False,
        )

    assert db.added == []


def test_invite_lock_unlock_revoke_lifecycle_on_existing_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(users_service, "_ensure_workspace_exists", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(users_service, "_unique_username", lambda *_args, **_kwargs: "worker")
    monkeypatch.setattr(users_service, "_hash_password", lambda *_args, **_kwargs: ("salt", "hash"))
    monkeypatch.setattr(users_service, "_now", lambda: now)

    user_row = SimpleNamespace(user_id="worker@tenant.local", email="worker@tenant.local")
    db = _FakeCredentialDB(user_row=user_row, credential_row=None)

    invite_out = users_service.issue_user_invite(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-cred-01",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
        payload={"invite_ttl_hours": 12, "invite_base_url": "https://tenant.local/invite"},
        reset_existing=False,
    )
    assert invite_out["ok"] is True
    assert invite_out["credential"]["status"] == "PENDING_INVITE"
    assert isinstance(invite_out.get("invite_token"), str) and len(invite_out["invite_token"]) > 20
    assert str(invite_out.get("invite_url") or "").startswith("https://tenant.local/invite")

    lock_out = users_service.lock_user_credential(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-cred-01",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
        payload={"lock_for_minutes": 30},
    )
    assert lock_out["credential"]["status"] == "LOCKED"

    unlock_out = users_service.unlock_user_credential(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-cred-01",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
        payload={},
    )
    assert unlock_out["credential"]["status"] == "ACTIVE"

    db.credential_row.status = "PENDING_INVITE"
    revoke_out = users_service.revoke_user_invite(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-cred-01",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
    )
    assert revoke_out["credential"]["status"] == "DISABLED"


def test_profile_and_users_invite_routes_call_canonical_users_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str, str]] = []

    def _spy_issue_invite(db, *, workspace_type: str, workspace_id: str, user_id: str, actor: str, payload: dict, reset_existing: bool = False):
        calls.append((workspace_type, workspace_id, user_id, actor))
        return {
            "ok": True,
            "credential": {"status": "PENDING_INVITE"},
            "invite_token": "token",
            "invite_url": None,
            "invite_expires_at": "2026-03-22T12:00:00+00:00",
            "mode": "INVITE_ISSUE",
        }

    monkeypatch.setattr(users_service, "issue_user_invite", _spy_issue_invite)
    monkeypatch.setattr(users_admin_user_domain, "write_audit", lambda *_args, **_kwargs: None)

    claims = {"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-cred-01", "sub": "admin@tenant.local"}

    out_profile = profile_admin_user_domain.issue_user_invite(
        user_id="worker@tenant.local",
        payload={},
        workspace=None,
        claims=claims,
        db=_DummyDB(),
    )
    out_users = users_admin_user_domain.issue_user_invite(
        user_id="worker@tenant.local",
        payload={},
        workspace=None,
        claims=claims,
        db=_DummyDB(),
    )

    assert out_profile["ok"] is True
    assert out_users["ok"] is True
    assert calls == [
        ("TENANT", "tenant-cred-01", "worker@tenant.local", "admin@tenant.local"),
        ("TENANT", "tenant-cred-01", "worker@tenant.local", "admin@tenant.local"),
    ]


def test_invite_route_maps_business_conflict_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ValueError("invite_already_pending")

    monkeypatch.setattr(users_service, "issue_user_invite", _raise)

    with pytest.raises(HTTPException) as exc:
        users_admin_user_domain.issue_user_invite(
            user_id="worker@tenant.local",
            payload={},
            workspace=None,
            claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-cred-01", "sub": "admin@tenant.local"},
            db=_DummyDB(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "invite_already_pending"


def test_service_provision_workspace_user_orchestrates_membership_roles_and_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _upsert(*_args, **_kwargs):
        calls.append("upsert")
        return {"user_id": "worker@tenant.local", "roles": []}

    def _set_roles(*_args, **_kwargs):
        calls.append("set_roles")
        return {"user_id": "worker@tenant.local", "roles": ["DISPATCHER"]}

    def _invite(*_args, **_kwargs):
        calls.append("invite")
        return {"ok": True, "credential": {"status": "PENDING_INVITE"}, "mode": "INVITE_ISSUE"}

    monkeypatch.setattr(users_service, "upsert_workspace_user", _upsert)
    monkeypatch.setattr(users_service, "set_workspace_user_roles", _set_roles)
    monkeypatch.setattr(users_service, "issue_user_invite", _invite)

    out = users_service.provision_workspace_user(
        _DummyDB(),
        workspace_type="TENANT",
        workspace_id="tenant-cred-01",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
        payload={
            "user": {"email": "worker@tenant.local", "display_name": "Worker"},
            "role_codes": ["DISPATCHER"],
            "credential_mode": "INVITE",
            "credentials": {"invite_ttl_hours": 24},
        },
    )

    assert out["ok"] is True
    assert out["workspace_user"]["roles"] == ["DISPATCHER"]
    assert out["credential_mode"] == "INVITE"
    assert out["credentials"]["credential"]["status"] == "PENDING_INVITE"
    assert calls == ["upsert", "set_roles", "invite"]


def test_profile_and_users_provision_routes_call_same_canonical_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str, str]] = []

    def _spy_provision(db, *, workspace_type: str, workspace_id: str, user_id: str, payload: dict, actor: str):
        calls.append((workspace_type, workspace_id, user_id, actor))
        return {"ok": True, "workspace_user": {"user_id": user_id}, "credential_mode": "INVITE", "credentials": None}

    monkeypatch.setattr(users_service, "provision_workspace_user", _spy_provision)
    monkeypatch.setattr(users_admin_workspace, "write_audit", lambda *_args, **_kwargs: None)

    claims = {"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-cred-01", "sub": "admin@tenant.local"}
    payload = {"user": {"email": "worker@tenant.local"}, "credential_mode": "NONE"}

    out_profile = profile_admin_workspace.provision_user(
        user_id="worker@tenant.local",
        payload=payload,
        workspace=None,
        claims=claims,
        db=_DummyDB(),
    )
    out_users = users_admin_workspace.provision_user(
        user_id="worker@tenant.local",
        payload=payload,
        workspace=None,
        claims=claims,
        db=_DummyDB(),
    )

    assert out_profile["ok"] is True
    assert out_users["ok"] is True
    assert calls == [
        ("TENANT", "tenant-cred-01", "worker@tenant.local", "admin@tenant.local"),
        ("TENANT", "tenant-cred-01", "worker@tenant.local", "admin@tenant.local"),
    ]


def test_provision_route_maps_credential_conflict_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ValueError("credentials_already_issued")

    monkeypatch.setattr(users_service, "provision_workspace_user", _raise)

    with pytest.raises(HTTPException) as exc:
        users_admin_workspace.provision_user(
            user_id="worker@tenant.local",
            payload={},
            workspace=None,
            claims={"roles": ["TENANT_ADMIN"], "tenant_id": "tenant-cred-01", "sub": "admin@tenant.local"},
            db=_DummyDB(),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "credentials_already_issued"
