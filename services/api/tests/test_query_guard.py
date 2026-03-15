from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.middleware import QueryGuardMiddleware


def _build_app(max_limit: int = 50) -> FastAPI:
    app = FastAPI()
    app.add_middleware(QueryGuardMiddleware, max_list_limit=max_limit)

    @app.get("/probe")
    def probe(request: Request) -> dict:
        return {
            "raw": request.url.query,
            "limit": request.query_params.get("limit"),
            "offset": request.query_params.get("offset"),
        }

    return app


def test_query_guard_clamps_over_limit() -> None:
    c = TestClient(_build_app(max_limit=100))
    r = c.get("/probe", params={"limit": 999, "offset": 10})
    assert r.status_code == 200
    payload = r.json()
    assert payload["limit"] == "100"
    assert payload["offset"] == "10"


def test_query_guard_clamps_to_min_one() -> None:
    c = TestClient(_build_app(max_limit=100))
    r = c.get("/probe", params={"limit": 0})
    assert r.status_code == 200
    assert r.json()["limit"] == "1"


def test_query_guard_keeps_non_numeric_limit() -> None:
    c = TestClient(_build_app(max_limit=100))
    r = c.get("/probe?limit=abc&offset=5")
    assert r.status_code == 200
    payload = r.json()
    assert payload["limit"] == "abc"
    assert payload["offset"] == "5"


def test_query_guard_no_limit_param_unchanged() -> None:
    c = TestClient(_build_app(max_limit=100))
    r = c.get("/probe", params={"offset": 20})
    assert r.status_code == 200
    payload = r.json()
    assert payload["limit"] is None
    assert payload["offset"] == "20"