from __future__ import annotations

from collections import deque
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
import time

from app.core.settings import get_settings


@dataclass
class _RequestSample:
    method: str
    path: str
    request_id: str | None
    started_perf_counter: float
    segments_ms: dict[str, float] = field(default_factory=dict)


class _MetricWindow:
    def __init__(self, window_size: int) -> None:
        self.samples: deque[float] = deque(maxlen=max(64, int(window_size)))
        self.count: int = 0
        self.total_ms: float = 0.0
        self.max_ms: float = 0.0

    def configure(self, window_size: int) -> None:
        win = max(64, int(window_size))
        if self.samples.maxlen != win:
            self.samples = deque(list(self.samples)[-win:], maxlen=win)

    def add(self, value_ms: float) -> None:
        v = max(0.0, float(value_ms))
        self.count += 1
        self.total_ms += v
        if v > self.max_ms:
            self.max_ms = v
        self.samples.append(v)

    def _pct(self, p: float) -> float:
        vals = list(self.samples)
        if not vals:
            return 0.0
        vals.sort()
        if len(vals) == 1:
            return float(vals[0])
        idx = int(round((max(0.0, min(100.0, float(p))) / 100.0) * (len(vals) - 1)))
        return float(vals[idx])

    def snapshot(self) -> dict[str, Any]:
        return {
            "count": int(self.count),
            "window_samples": int(len(self.samples)),
            "total_ms": round(float(self.total_ms), 3),
            "avg_ms": round(float(self.total_ms) / max(1, int(self.count)), 3),
            "p50_ms": round(self._pct(50), 3),
            "p95_ms": round(self._pct(95), 3),
            "p99_ms": round(self._pct(99), 3),
            "max_ms": round(float(self.max_ms), 3),
        }


class _PerfState:
    def __init__(self) -> None:
        self._lock = Lock()
        self.started_at = datetime.now(timezone.utc)
        self.window_size = 4096
        self.total_requests = 0
        self.status_counts: dict[str, int] = {}
        self.segments: dict[str, _MetricWindow] = {}

    def configure(self, *, window_size: int) -> None:
        win = max(64, int(window_size))
        with self._lock:
            self.window_size = win
            for metric in self.segments.values():
                metric.configure(win)

    def reset(self) -> None:
        with self._lock:
            self.started_at = datetime.now(timezone.utc)
            self.total_requests = 0
            self.status_counts = {}
            self.segments = {}

    def record(self, *, sample: _RequestSample, status_code: int) -> None:
        with self._lock:
            self.total_requests += 1
            key = str(int(status_code))
            self.status_counts[key] = int(self.status_counts.get(key, 0)) + 1

            for seg_name, seg_ms in (sample.segments_ms or {}).items():
                metric = self.segments.get(seg_name)
                if metric is None:
                    metric = _MetricWindow(self.window_size)
                    self.segments[seg_name] = metric
                metric.add(seg_ms)

    def snapshot(self, *, enabled: bool, methods: list[str], prefixes: list[str]) -> dict[str, Any]:
        with self._lock:
            seg = {k: v.snapshot() for k, v in sorted(self.segments.items(), key=lambda item: item[0])}
            status_counts = {k: int(v) for k, v in sorted(self.status_counts.items(), key=lambda item: item[0])}
            return {
                "enabled": bool(enabled),
                "started_at": self.started_at.isoformat(),
                "filters": {
                    "methods": list(methods),
                    "path_prefixes": list(prefixes),
                },
                "window_size": int(self.window_size),
                "total_requests": int(self.total_requests),
                "status_counts": status_counts,
                "segments": seg,
            }


_REQUEST_SAMPLE: ContextVar[_RequestSample | None] = ContextVar("mydata_perf_request_sample", default=None)
_STATE = _PerfState()


def _parse_csv(raw: str | None) -> list[str]:
    out: list[str] = []
    for item in str(raw or "").split(","):
        val = str(item or "").strip()
        if val and val not in out:
            out.append(val)
    return out


def _config() -> tuple[bool, list[str], list[str], int]:
    s = get_settings()
    enabled = bool(s.perf_profiling_enabled)
    methods = [x.upper() for x in _parse_csv(s.perf_profiling_methods or "GET")]
    prefixes = _parse_csv(s.perf_profiling_path_prefixes or "/orders")
    window = max(64, int(s.perf_profiling_window_size))
    return enabled, methods, prefixes, window


def _should_profile(*, method: str, path: str, methods: list[str], prefixes: list[str]) -> bool:
    m = str(method or "").upper()
    p = str(path or "")
    if methods and m not in methods:
        return False
    if prefixes and not any(p.startswith(px) for px in prefixes):
        return False
    return True


def start_request_profile(*, method: str, path: str, request_id: str | None = None) -> Token | None:
    enabled, methods, prefixes, window = _config()
    _STATE.configure(window_size=window)

    if not enabled:
        return None
    if not _should_profile(method=method, path=path, methods=methods, prefixes=prefixes):
        return None

    sample = _RequestSample(
        method=str(method or "").upper(),
        path=str(path or ""),
        request_id=(str(request_id).strip() if request_id else None),
        started_perf_counter=time.perf_counter(),
        segments_ms={},
    )
    return _REQUEST_SAMPLE.set(sample)


def record_segment(name: str, value_ms: float) -> None:
    sample = _REQUEST_SAMPLE.get()
    if sample is None:
        return

    key = str(name or "").strip()
    if not key:
        return

    v = max(0.0, float(value_ms))
    sample.segments_ms[key] = float(sample.segments_ms.get(key, 0.0)) + v


def is_request_profile_active() -> bool:
    return _REQUEST_SAMPLE.get() is not None


def end_request_profile(*, status_code: int, token: Token | None = None) -> None:
    sample = _REQUEST_SAMPLE.get()
    if sample is None:
        if token is not None:
            _REQUEST_SAMPLE.reset(token)
        return

    wall_ms = (time.perf_counter() - float(sample.started_perf_counter)) * 1000.0
    sample.segments_ms.setdefault("request_wall_ms", max(0.0, float(wall_ms)))

    _STATE.record(sample=sample, status_code=int(status_code))

    if token is not None:
        _REQUEST_SAMPLE.reset(token)
    else:
        _REQUEST_SAMPLE.set(None)


def get_perf_snapshot() -> dict[str, Any]:
    enabled, methods, prefixes, _window = _config()
    return _STATE.snapshot(enabled=enabled, methods=methods, prefixes=prefixes)


def reset_perf_snapshot() -> None:
    _STATE.reset()
