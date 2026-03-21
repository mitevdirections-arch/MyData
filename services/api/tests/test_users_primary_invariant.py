from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.db.models import WorkspaceUserAddress, WorkspaceUserContactChannel, WorkspaceUserNextOfKin
from app.modules.users.service import service as users_service


class _PrimaryQuery:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs) -> "_PrimaryQuery":
        return self

    def order_by(self, *_args, **_kwargs) -> "_PrimaryQuery":
        self._rows.sort(key=lambda x: (int(x.sort_order or 0), x.created_at, str(x.id)))
        return self

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)


class _PrimaryDB:
    def __init__(self, rows_by_model: dict[type, list[SimpleNamespace]]) -> None:
        self._rows_by_model = rows_by_model
        self.flush_calls = 0

    def query(self, model):
        return _PrimaryQuery(self._rows_by_model.setdefault(model, []))

    def flush(self) -> None:
        self.flush_calls += 1


def _row(*, sort_order: int, is_primary: bool, minute: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        is_primary=bool(is_primary),
        sort_order=int(sort_order),
        created_at=datetime(2026, 3, 22, 12, minute, tzinfo=timezone.utc),
        updated_by=None,
        updated_at=None,
    )


@pytest.mark.parametrize(
    "model",
    [WorkspaceUserContactChannel, WorkspaceUserAddress, WorkspaceUserNextOfKin],
)
def test_primary_invariant_promotes_lowest_sort_order_when_no_primary(model) -> None:
    first = _row(sort_order=20, is_primary=False, minute=2)
    second = _row(sort_order=10, is_primary=False, minute=1)
    db = _PrimaryDB({model: [first, second]})

    chosen = users_service._enforce_exactly_one_primary(
        db,
        model=model,
        workspace_type="TENANT",
        workspace_id="tenant-primary",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
    )

    assert chosen is second
    assert second.is_primary is True
    assert first.is_primary is False
    assert db.flush_calls == 1


@pytest.mark.parametrize(
    "model",
    [WorkspaceUserContactChannel, WorkspaceUserAddress, WorkspaceUserNextOfKin],
)
def test_primary_invariant_respects_preferred_row(model) -> None:
    first = _row(sort_order=10, is_primary=True, minute=1)
    second = _row(sort_order=20, is_primary=False, minute=2)
    db = _PrimaryDB({model: [first, second]})

    chosen = users_service._enforce_exactly_one_primary(
        db,
        model=model,
        workspace_type="TENANT",
        workspace_id="tenant-primary",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
        preferred_id=second.id,
    )

    assert chosen is second
    assert second.is_primary is True
    assert first.is_primary is False
    assert db.flush_calls == 1


@pytest.mark.parametrize(
    "model",
    [WorkspaceUserContactChannel, WorkspaceUserAddress, WorkspaceUserNextOfKin],
)
def test_primary_invariant_promotes_next_after_primary_removed(model) -> None:
    surviving = _row(sort_order=50, is_primary=False, minute=5)
    db = _PrimaryDB({model: [surviving]})

    chosen = users_service._enforce_exactly_one_primary(
        db,
        model=model,
        workspace_type="TENANT",
        workspace_id="tenant-primary",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
    )

    assert chosen is surviving
    assert surviving.is_primary is True
    assert db.flush_calls == 1


@pytest.mark.parametrize(
    "model",
    [WorkspaceUserContactChannel, WorkspaceUserAddress, WorkspaceUserNextOfKin],
)
def test_primary_invariant_no_rows_no_change(model) -> None:
    db = _PrimaryDB({model: []})

    chosen = users_service._enforce_exactly_one_primary(
        db,
        model=model,
        workspace_type="TENANT",
        workspace_id="tenant-primary",
        user_id="worker@tenant.local",
        actor="admin@tenant.local",
    )

    assert chosen is None
    assert db.flush_calls == 0
