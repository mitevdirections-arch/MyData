import pytest

import app.db.session as db_session


class _DummyConn:
    def __init__(self) -> None:
        self.info: dict[str, int] = {}

    def exec_driver_sql(self, _sql: str) -> None:
        return None


class _DummySession:
    def __init__(self) -> None:
        self._conn = _DummyConn()
        self.closed = False

    def connection(self) -> _DummyConn:
        return self._conn

    def close(self) -> None:
        self.closed = True


class _Settings:
    db_statement_timeout_ms = 1000


def test_get_db_session_records_dependency_segments(monkeypatch) -> None:
    emitted: list[str] = []
    bound: list[tuple[bool, bool]] = []

    dummy = _DummySession()

    monkeypatch.setattr(db_session, "record_segment", lambda name, _value: emitted.append(str(name)))
    monkeypatch.setattr(db_session, "get_current_claims", lambda: {"tenant_id": "tenant-x", "sub": "user-x"})
    monkeypatch.setattr(
        db_session,
        "bind_rls_context",
        lambda _db, claims, enabled: bound.append((bool(enabled), bool(claims))),
    )
    monkeypatch.setattr(db_session, "get_settings", lambda: _Settings())
    monkeypatch.setattr(db_session, "get_session_factory", lambda: (lambda: dummy))

    gen = db_session.get_db_session()
    out = next(gen)
    assert out is dummy

    with pytest.raises(StopIteration):
        next(gen)

    assert dummy.closed is True
    assert bound and bound[0] == (True, True)

    required = {
        "session_open_ms",
        "connection_acquire_ms",
        "session_timeout_setup_ms",
        "rls_bind_ms",
        "dependency_overhead_ms",
    }
    assert required.issubset(set(emitted))
