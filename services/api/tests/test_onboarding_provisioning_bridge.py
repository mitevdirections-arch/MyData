from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.modules.onboarding.service as onboarding_service_module
from app.modules.onboarding.service import service as onboarding_service


class _FakeQuery:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._row

    def update(self, values: dict, **_kwargs) -> int:
        if self._row is None:
            return 0
        current = str(getattr(self._row, "status", "") or "").upper()
        if current != "SUBMITTED":
            return 0
        if isinstance(values, dict):
            for key, val in values.items():
                if key == "status" or str(getattr(key, "key", "")).lower() == "status":
                    setattr(self._row, "status", val)
                    break
        if str(getattr(self._row, "status", "") or "").upper() != "APPROVING":
            setattr(self._row, "status", "APPROVING")
        return 1


class _FakeDB:
    def __init__(self, row: object | None) -> None:
        self._row = row
        self.commits = 0
        self.refresh_calls = 0
        self.rollbacks = 0

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(self._row)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj: object) -> None:
        self.refresh_calls += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _application(*, seat_count: int, core_plan_code: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status="SUBMITTED",
        legal_name="Acme Logistics",
        country_code="BG",
        contact_email="owner@acme.local",
        seat_count=int(seat_count),
        core_plan_code=core_plan_code,
        default_locale="bg-BG",
        default_time_zone="Europe/Sofia",
        date_style="DMY",
        time_style="24H",
        unit_system="METRIC",
        payload_json={"vat_number": "BG123456789"},
        created_at=datetime.now(timezone.utc),
    )


def test_approve_application_bridges_to_provisioning_with_canonical_core_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    app_row = _application(seat_count=8, core_plan_code="CORE_U8")
    db = _FakeDB(app_row)
    captured: dict[str, object] = {}

    def _fake_run_tenant_provisioning(_db, *, payload, actor):
        captured["payload"] = payload
        captured["actor"] = actor
        return {"ok": True, "summary": {"tenant_id": payload.get("tenant_id")}}

    monkeypatch.setattr(
        onboarding_service_module.provisioning_service,
        "run_tenant_provisioning",
        _fake_run_tenant_provisioning,
    )

    out = onboarding_service.approve_application_and_provision(
        db=db,
        application_id=str(app_row.id),
        actor="superadmin@ops.local",
        payload={
            "tenant_id": "tenant-acme",
            "core_plan_code": "CORE_U13",
            "admin": {"user_id": "owner@acme.local"},
        },
    )

    assert out["ok"] is True
    assert app_row.status == "APPROVED"
    assert db.commits == 2
    assert db.refresh_calls == 1
    assert captured["actor"] == "superadmin@ops.local"

    provisioning_payload = dict(captured["payload"] or {})
    issuance = dict(provisioning_payload.get("issuance") or {})
    assert provisioning_payload.get("tenant_id") == "tenant-acme"
    assert issuance.get("issue_startup") is True
    assert issuance.get("admin_confirmed") is True
    assert issuance.get("core_plan_code") == "CORE13"


def test_approve_application_uses_onboarding_selected_plan_when_payload_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    app_row = _application(seat_count=5, core_plan_code="CORE_U5")
    db = _FakeDB(app_row)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        onboarding_service_module.provisioning_service,
        "run_tenant_provisioning",
        lambda _db, *, payload, actor: captured.update({"payload": payload, "actor": actor}) or {"ok": True, "summary": {"tenant_id": payload.get("tenant_id")}},
    )

    out = onboarding_service.approve_application_and_provision(
        db=db,
        application_id=str(app_row.id),
        actor="superadmin@ops.local",
        payload={
            "tenant_id": "tenant-onboarding",
            "admin": {"user_id": "owner@acme.local"},
        },
    )

    assert out["ok"] is True
    issuance = dict((captured.get("payload") or {}).get("issuance") or {})
    assert issuance.get("core_plan_code") == "CORE5"
    assert app_row.status == "APPROVED"
    assert db.commits == 2
    assert db.refresh_calls == 1


def test_approve_application_rejects_when_already_in_progress() -> None:
    app_row = _application(seat_count=5, core_plan_code="CORE_U5")
    app_row.status = "APPROVING"
    db = _FakeDB(app_row)

    with pytest.raises(ValueError, match="application_approval_in_progress"):
        onboarding_service.approve_application_and_provision(
            db=db,
            application_id=str(app_row.id),
            actor="superadmin@ops.local",
            payload={
                "tenant_id": "tenant-onboarding",
                "admin": {"user_id": "owner@acme.local"},
            },
        )


def test_approve_application_releases_lock_state_on_provisioning_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    app_row = _application(seat_count=5, core_plan_code="CORE_U5")
    db = _FakeDB(app_row)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("provisioning_failed")

    monkeypatch.setattr(onboarding_service_module.provisioning_service, "run_tenant_provisioning", _boom)

    with pytest.raises(RuntimeError, match="provisioning_failed"):
        onboarding_service.approve_application_and_provision(
            db=db,
            application_id=str(app_row.id),
            actor="superadmin@ops.local",
            payload={
                "tenant_id": "tenant-onboarding",
                "admin": {"user_id": "owner@acme.local"},
            },
        )

    assert app_row.status == "SUBMITTED"
    assert db.commits == 2
    assert db.refresh_calls == 1
