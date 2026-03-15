from app.core.perf_profile import reset_perf_snapshot
from app.core.settings import get_settings
from app.main import create_app
from fastapi.testclient import TestClient


def _reset_state() -> None:
    get_settings.cache_clear()
    reset_perf_snapshot()


def test_perf_snapshot_default_disabled(monkeypatch) -> None:
    monkeypatch.delenv("PERF_PROFILING_ENABLED", raising=False)
    _reset_state()
    try:
        client = TestClient(create_app())
        r = client.get("/healthz/perf")
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        prof = payload.get("profiling") or {}
        assert prof.get("enabled") is False
    finally:
        _reset_state()


def test_perf_snapshot_collects_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("PERF_PROFILING_ENABLED", "true")
    monkeypatch.setenv("PERF_PROFILING_PATH_PREFIXES", "/public/country-engine")
    monkeypatch.setenv("PERF_PROFILING_METHODS", "GET")
    monkeypatch.setenv("API_RUNTIME_TIMING_HEADERS_ENABLED", "true")
    _reset_state()
    try:
        client = TestClient(create_app())
        rr = client.post("/healthz/perf/reset")
        assert rr.status_code == 200

        r = client.get("/public/country-engine/version")
        assert r.status_code == 200

        snap = client.get("/healthz/perf")
        assert snap.status_code == 200
        prof = (snap.json() or {}).get("profiling") or {}
        assert prof.get("enabled") is True
        assert int(prof.get("total_requests") or 0) >= 1

        segments = prof.get("segments") or {}
        assert "process_time_ms" in segments
        assert "queue_wait_ms" in segments
        assert "middleware_total_ms" in segments
        assert "total_request_ms" in segments
        assert "request_wall_ms" in segments
    finally:
        _reset_state()


def test_perf_snapshot_collects_token_verify_for_protected_route(monkeypatch) -> None:
    monkeypatch.setenv("PERF_PROFILING_ENABLED", "true")
    monkeypatch.setenv("PERF_PROFILING_PATH_PREFIXES", "/orders")
    monkeypatch.setenv("PERF_PROFILING_METHODS", "GET")
    _reset_state()
    try:
        client = TestClient(create_app())
        rr = client.post("/healthz/perf/reset")
        assert rr.status_code == 200

        r = client.get("/orders?limit=1", headers={"Authorization": "Bearer invalid"})
        assert r.status_code == 401

        snap = client.get("/healthz/perf")
        assert snap.status_code == 200
        prof = (snap.json() or {}).get("profiling") or {}
        segments = prof.get("segments") or {}

        assert "token_verify_ms" in segments
        assert "middleware_total_ms" in segments
        assert "total_request_ms" in segments
    finally:
        _reset_state()
