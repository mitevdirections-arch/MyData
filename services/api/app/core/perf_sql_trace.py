from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import os
from typing import Iterator

_SQL_TRACE_ZONE: ContextVar[str | None] = ContextVar("mydata_sql_trace_zone", default=None)


def is_sql_trace_enabled() -> bool:
    raw = str(os.getenv("MYDATA_PERF_SQL_TRACE", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_sql_trace_zone() -> str | None:
    zone = _SQL_TRACE_ZONE.get()
    if not isinstance(zone, str):
        return None
    out = zone.strip().lower()
    return out or None


@contextmanager
def sql_trace_zone(zone: str | None) -> Iterator[None]:
    if not is_sql_trace_enabled():
        yield
        return

    raw = str(zone or "").strip().lower()
    token: Token = _SQL_TRACE_ZONE.set(raw or None)
    try:
        yield
    finally:
        _SQL_TRACE_ZONE.reset(token)
