from __future__ import annotations

from types import SimpleNamespace

from app.core.authz_fast_path import resolve_effective_permissions_from_fast_path


class _FastQuery:
    def __init__(self, db: "_FastDB") -> None:
        self._db = db

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._db.row


class _FastDB:
    def __init__(self, row=None) -> None:
        self.row = row
        self.query_calls = 0

    def query(self, *_args, **_kwargs):
        self.query_calls += 1
        return _FastQuery(self)


def _row(*, status: str = "ACTIVE", perms=None, source_version: int = 1):
    return SimpleNamespace(
        employment_status=status,
        effective_permissions_json=list(perms or []),
        source_version=int(source_version),
    )


def test_fast_path_missing_row_is_invalid() -> None:
    db = _FastDB(row=None)

    out = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-x",
        user_id="user@tenant.local",
        required_source_version=1,
    )

    assert out["found"] is False
    assert out["valid"] is False
    assert out["reason"] == "missing"
    assert db.query_calls == 1


def test_fast_path_stale_source_version_is_invalid() -> None:
    db = _FastDB(row=_row(status="ACTIVE", perms=["ORDERS.READ"], source_version=2))

    out = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-x",
        user_id="user@tenant.local",
        required_source_version=7,
    )

    assert out["found"] is True
    assert out["valid"] is False
    assert out["reason"] == "stale_source_version"


def test_fast_path_inactive_employment_denies() -> None:
    db = _FastDB(row=_row(status="INACTIVE", perms=["ORDERS.READ"], source_version=1))

    out = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-x",
        user_id="user@tenant.local",
        required_source_version=1,
    )

    assert out["found"] is True
    assert out["valid"] is True
    assert out["reason"] == "inactive_employment"
    assert out["effective_permissions"] == []


def test_fast_path_invalid_permissions_payload_denies() -> None:
    row = SimpleNamespace(employment_status="ACTIVE", effective_permissions_json={"ORDERS.READ": True}, source_version=1)
    db = _FastDB(row=row)

    out = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-x",
        user_id="user@tenant.local",
        required_source_version=1,
    )

    assert out["found"] is True
    assert out["valid"] is False
    assert out["reason"] == "invalid_permissions_payload"


def test_fast_path_normalizes_and_dedupes_permissions() -> None:
    db = _FastDB(row=_row(status="ACTIVE", perms=["orders.read", "ORDERS.READ", " iam.read ", ""], source_version=1))

    out = resolve_effective_permissions_from_fast_path(
        db,
        workspace_type="TENANT",
        workspace_id="tenant-x",
        user_id="user@tenant.local",
        required_source_version=1,
    )

    assert out["found"] is True
    assert out["valid"] is True
    assert out["reason"] == "ok"
    assert set(out["effective_permissions"]) == {"ORDERS.READ", "IAM.READ"}
