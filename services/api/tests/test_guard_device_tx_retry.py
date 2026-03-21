from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.guard.service import GuardService


class _FakeSession:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.rollback_calls = 0
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1
        if self._error is not None:
            raise self._error

    def rollback(self) -> None:
        self.rollback_calls += 1


class _RetryableDBError(Exception):
    sqlstate = "40001"


class _NonRetryableDBError(Exception):
    sqlstate = "22001"


def test_commit_transition_maps_integrity_conflict_to_retry_code() -> None:
    svc = GuardService()
    db = _FakeSession(error=IntegrityError("stmt", {}, Exception("unique_violation")))

    with pytest.raises(ValueError, match="DEVICE_STATE_CONFLICT_RETRY"):
        svc._commit_device_transition(db)  # noqa: SLF001

    assert db.rollback_calls == 1


def test_commit_transition_maps_retryable_operational_error_to_retry_code() -> None:
    svc = GuardService()
    op_err = OperationalError("commit", {}, _RetryableDBError("restart transaction"))
    db = _FakeSession(error=op_err)

    with pytest.raises(ValueError, match="DEVICE_STATE_CONFLICT_RETRY"):
        svc._commit_device_transition(db)  # noqa: SLF001

    assert db.rollback_calls == 1


def test_commit_transition_propagates_non_retryable_operational_error() -> None:
    svc = GuardService()
    op_err = OperationalError("commit", {}, _NonRetryableDBError("value too long"))
    db = _FakeSession(error=op_err)

    with pytest.raises(OperationalError):
        svc._commit_device_transition(db)  # noqa: SLF001

    assert db.rollback_calls == 1
