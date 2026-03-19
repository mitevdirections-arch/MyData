from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.licensing.service import LicensingService


class _FakeQuery:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        if self._db.raise_on_first:
            raise RuntimeError("db_down")
        return self._db.row


class _FakeExecuteResult:
    def __init__(self, db: "_FakeDB") -> None:
        self._db = db

    def first(self):
        if self._db.raise_on_first:
            raise RuntimeError("db_down")
        return self._db.row


class _FakeDB:
    def __init__(self, *, row=None, raise_on_first: bool = False) -> None:
        self.row = row
        self.raise_on_first = bool(raise_on_first)
        self.total_calls = 0
        self.query_calls = 0
        self.execute_calls = 0

    def query(self, *_args, **_kwargs):
        self.total_calls += 1
        self.query_calls += 1
        return _FakeQuery(self)

    def execute(self, *_args, **_kwargs):
        self.total_calls += 1
        self.execute_calls += 1
        return _FakeExecuteResult(self)


def test_resolve_module_entitlement_empty_module_code_short_circuit() -> None:
    svc = LicensingService()
    db = _FakeDB()

    out = svc.resolve_module_entitlement(db, "tenant-x", "")

    assert out["allowed"] is False
    assert out["reason"] == "module_code_required"
    assert db.total_calls == 0


def test_resolve_module_entitlement_startup_allow_single_query() -> None:
    svc = LicensingService()
    now = datetime.now(timezone.utc)
    db = _FakeDB(row=("STARTUP", uuid.uuid4(), now + timedelta(days=30)))

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is True
    assert out["reason"] == "startup_full_access"
    assert out["source"]["license_type"] == "STARTUP"
    assert db.total_calls == 1


def test_resolve_module_entitlement_module_allow_single_query() -> None:
    svc = LicensingService()
    now = datetime.now(timezone.utc)
    db = _FakeDB(row=("MODULE_TRIAL", uuid.uuid4(), now + timedelta(days=10)))

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is True
    assert out["reason"] == "module_license_active"
    assert out["source"]["license_type"] == "MODULE_TRIAL"
    assert db.total_calls == 1


def test_resolve_module_entitlement_missing_truth_denies() -> None:
    svc = LicensingService()
    db = _FakeDB(row=None)

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is False
    assert out["reason"] == "module_license_required"
    assert db.total_calls == 1


def test_resolve_module_entitlement_db_error_fail_closed() -> None:
    svc = LicensingService()
    db = _FakeDB(raise_on_first=True)

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is False
    assert out["reason"] == "module_license_required"
    assert db.total_calls == 1


def test_resolve_module_entitlement_legacy_mode_uses_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYDATA_PERF_ENTITLEMENT_QUERY_MODE", "legacy")
    svc = LicensingService()
    now = datetime.now(timezone.utc)
    db = _FakeDB(row=("MODULE_TRIAL", uuid.uuid4(), now + timedelta(days=10)))

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is True
    assert out["reason"] == "module_license_active"
    assert db.query_calls == 1
    assert db.execute_calls == 0


def test_resolve_module_entitlement_invalid_mode_falls_back_to_legacy_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYDATA_PERF_ENTITLEMENT_QUERY_MODE", "invalid-mode")
    svc = LicensingService()
    now = datetime.now(timezone.utc)
    db = _FakeDB(row=("STARTUP", uuid.uuid4(), now + timedelta(days=30)))

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is True
    assert out["reason"] == "startup_full_access"
    assert db.query_calls == 1
    assert db.execute_calls == 0


def test_resolve_module_entitlement_default_mode_is_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYDATA_PERF_ENTITLEMENT_QUERY_MODE", raising=False)
    svc = LicensingService()
    now = datetime.now(timezone.utc)
    db = _FakeDB(row=("STARTUP", uuid.uuid4(), now + timedelta(days=30)))

    out = svc.resolve_module_entitlement(db, "tenant-x", "MODULE_ORDERS")

    assert out["allowed"] is True
    assert out["reason"] == "startup_full_access"
    assert db.query_calls == 1
    assert db.execute_calls == 0
