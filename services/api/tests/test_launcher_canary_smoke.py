from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.route_ownership import (
    ROUTE_PLANE_FOUNDATION,
    ROUTE_PLANE_OPERATIONAL,
    ROUTE_PLANE_OWNERSHIP,
)
from app.launcher.composition import plane_owned_route_keys
from app.main_foundation_canary import app as foundation_canary_app
from app.main_operational_canary import app as operational_canary_app


def _app_route_keys(app) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(set(route.methods or set()))
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.add((method, route.path))
    return out


def test_foundation_canary_boot_and_openapi_surface() -> None:
    with TestClient(foundation_canary_app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("paths"), dict)
    assert len(body["paths"]) > 0


def test_operational_canary_boot_and_openapi_surface() -> None:
    with TestClient(operational_canary_app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("paths"), dict)
    assert len(body["paths"]) > 0


def test_foundation_canary_has_no_operational_leakage() -> None:
    keys = _app_route_keys(foundation_canary_app).intersection(set(ROUTE_PLANE_OWNERSHIP.keys()))
    assert keys == plane_owned_route_keys(ROUTE_PLANE_FOUNDATION)
    assert keys.isdisjoint(plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL))


def test_operational_canary_has_no_foundation_leakage() -> None:
    keys = _app_route_keys(operational_canary_app).intersection(set(ROUTE_PLANE_OWNERSHIP.keys()))
    assert keys == plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL)
    assert keys.isdisjoint(plane_owned_route_keys(ROUTE_PLANE_FOUNDATION))
