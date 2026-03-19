from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import get_current_claims
from app.core.perf_profile import get_recorded_segment, record_segment
from app.core.perf_profile import is_request_profile_active
from app.core.perf_sql_trace import get_sql_trace_zone, is_sql_trace_enabled
from app.core.rls import bind_rls_context
from app.core.settings import get_settings


# Load .env from services/api root once at import time.
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=False)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def _protected_envelope_breakdown_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_PROTECTED_ENVELOPE_BREAKDOWN", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


@lru_cache
def get_engine():
    s = get_settings()
    engine = create_engine(
        _database_url(),
        pool_pre_ping=True,
        future=True,
        pool_size=max(5, int(s.db_pool_size)),
        max_overflow=max(0, int(s.db_max_overflow)),
        pool_timeout=max(1, int(s.db_pool_timeout_seconds)),
        pool_recycle=max(60, int(s.db_pool_recycle_seconds)),
        connect_args={"connect_timeout": 5},
    )
    _install_perf_sql_trace(engine)
    return engine


def _install_perf_sql_trace(engine) -> None:
    if getattr(engine, "_mydata_perf_sql_trace_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, _cursor, _statement, _parameters, _context, _executemany):  # noqa: ANN001
        if not is_sql_trace_enabled() or not is_request_profile_active():
            return
        stack = conn.info.setdefault("_mydata_perf_sql_trace_stack", [])
        stack.append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, _cursor, _statement, _parameters, _context, _executemany):  # noqa: ANN001
        if not is_sql_trace_enabled() or not is_request_profile_active():
            return

        stack = conn.info.get("_mydata_perf_sql_trace_stack")
        if not isinstance(stack, list) or not stack:
            return

        started = stack.pop()
        elapsed_ms = (time.perf_counter() - float(started)) * 1000.0
        record_segment("sql_query_count", 1.0)
        record_segment("sql_query_ms", elapsed_ms)

        zone = get_sql_trace_zone()
        if zone:
            record_segment(f"sql_query_count_{zone}", 1.0)
            record_segment(f"sql_query_ms_{zone}", elapsed_ms)

    setattr(engine, "_mydata_perf_sql_trace_installed", True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def _apply_session_timeouts(db: Session) -> tuple[float, float]:
    """Best-effort SQL timeout setup without per-request reconfiguration overhead."""
    connection_acquire_ms = 0.0
    session_timeout_setup_ms = 0.0

    s = get_settings()
    timeout_ms = max(0, int(s.db_statement_timeout_ms))
    if timeout_ms <= 0:
        return connection_acquire_ms, session_timeout_setup_ms

    try:
        conn_started = time.perf_counter()
        conn = db.connection()
        connection_acquire_ms = (time.perf_counter() - conn_started) * 1000.0

        info = getattr(conn, "info", None)
        if isinstance(info, dict) and int(info.get("statement_timeout_ms", -1)) == timeout_ms:
            return connection_acquire_ms, session_timeout_setup_ms

        # CockroachDB/Postgres style session statement timeout.
        setup_started = time.perf_counter()
        conn.exec_driver_sql(f"SET statement_timeout = {timeout_ms}")
        session_timeout_setup_ms = (time.perf_counter() - setup_started) * 1000.0

        if isinstance(info, dict):
            info["statement_timeout_ms"] = timeout_ms
    except Exception:  # noqa: BLE001
        # Non-fatal: API must stay available even if backend ignores this setting.
        return connection_acquire_ms, session_timeout_setup_ms

    return connection_acquire_ms, session_timeout_setup_ms


def get_db_session():
    dependency_started = time.perf_counter()

    session_open_started = time.perf_counter()
    db = get_session_factory()()
    session_open_ms = (time.perf_counter() - session_open_started) * 1000.0
    record_segment("session_open_ms", session_open_ms)

    connection_acquire_ms = 0.0
    session_timeout_setup_ms = 0.0
    rls_bind_ms = 0.0

    try:
        connection_acquire_ms, session_timeout_setup_ms = _apply_session_timeouts(db)
        record_segment("connection_acquire_ms", connection_acquire_ms)
        record_segment("session_timeout_setup_ms", session_timeout_setup_ms)

        rls_started = time.perf_counter()
        claims = get_current_claims()
        if isinstance(claims, dict) and claims:
            bind_rls_context(db, claims, enabled=True)
        else:
            bind_rls_context(db, {}, enabled=False)
        rls_bind_ms = (time.perf_counter() - rls_started) * 1000.0
        record_segment("rls_bind_ms", rls_bind_ms)

        dependency_total_ms = (time.perf_counter() - dependency_started) * 1000.0
        known_ms = session_open_ms + connection_acquire_ms + session_timeout_setup_ms + rls_bind_ms
        record_segment("dependency_overhead_ms", max(0.0, dependency_total_ms - known_ms))
        if _protected_envelope_breakdown_enabled() and is_request_profile_active():
            protected_session_acquire_ms = max(0.0, float(known_ms))
            existing_session_ms = get_recorded_segment("protected_session_acquire_ms")
            record_segment("protected_session_acquire_ms", protected_session_acquire_ms)
            envelope_known_ms = (
                get_recorded_segment("protected_token_verify_ms")
                + get_recorded_segment("protected_claims_prepare_ms")
                + get_recorded_segment("protected_policy_ms")
                + existing_session_ms
                + protected_session_acquire_ms
            )
            record_segment("protected_envelope_total_ms", max(0.0, float(envelope_known_ms)))

        yield db
    finally:
        db.close()
