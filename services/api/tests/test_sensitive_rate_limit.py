from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import SensitiveRateLimitMiddleware


def _build_app(*, write_limit: int, get_limit: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        SensitiveRateLimitMiddleware,
        max_requests_per_minute=write_limit,
        max_get_requests_per_minute=get_limit,
    )

    @app.get("/admin/storage/policy")
    def get_policy() -> dict:
        return {"ok": True}

    @app.post("/admin/storage/policy")
    def post_policy() -> dict:
        return {"ok": True}

    @app.get("/public/country-engine/version")
    def public_version() -> dict:
        return {"ok": True}

    return app


def test_sensitive_write_limited_get_allows_more() -> None:
    app = _build_app(write_limit=1, get_limit=100)
    c = TestClient(app)

    assert c.post("/admin/storage/policy").status_code == 200
    assert c.post("/admin/storage/policy").status_code == 429

    assert c.get("/admin/storage/policy").status_code == 200
    assert c.get("/admin/storage/policy").status_code == 200


def test_sensitive_get_limited_when_configured() -> None:
    app = _build_app(write_limit=10, get_limit=1)
    c = TestClient(app)

    assert c.get("/admin/storage/policy").status_code == 200
    assert c.get("/admin/storage/policy").status_code == 429


def test_public_routes_are_not_rate_limited() -> None:
    app = _build_app(write_limit=1, get_limit=1)
    c = TestClient(app)

    assert c.get("/public/country-engine/version").status_code == 200
    assert c.get("/public/country-engine/version").status_code == 200
    assert c.get("/public/country-engine/version").status_code == 200