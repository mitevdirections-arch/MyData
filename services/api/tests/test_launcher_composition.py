from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.route_ownership import (
    ROUTE_PLANE_FOUNDATION,
    ROUTE_PLANE_OPERATIONAL,
    ROUTE_PLANE_OWNERSHIP,
)
from app.launcher.composition import (
    launcher_composition_snapshot,
    plane_owned_route_keys,
    route_keys_from_router,
)
from app.launcher.foundation import create_foundation_router
from app.launcher.operational import create_operational_router
from app.main import app


def _app_route_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(set(route.methods or set()))
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            keys.add((method, route.path))
    return keys


def test_foundation_launcher_contains_only_foundation_routes() -> None:
    foundation_router = create_foundation_router()
    foundation_keys = route_keys_from_router(foundation_router).intersection(set(ROUTE_PLANE_OWNERSHIP.keys()))

    assert foundation_keys == plane_owned_route_keys(ROUTE_PLANE_FOUNDATION)
    assert foundation_keys.isdisjoint(plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL))


def test_operational_launcher_contains_only_operational_routes() -> None:
    operational_router = create_operational_router()
    operational_keys = route_keys_from_router(operational_router).intersection(set(ROUTE_PLANE_OWNERSHIP.keys()))

    assert operational_keys == plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL)
    assert operational_keys.isdisjoint(plane_owned_route_keys(ROUTE_PLANE_FOUNDATION))


def test_launcher_ownership_has_no_cross_plane_leakage() -> None:
    foundation_keys = plane_owned_route_keys(ROUTE_PLANE_FOUNDATION)
    operational_keys = plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL)

    assert foundation_keys.intersection(operational_keys) == set()

    snapshot = launcher_composition_snapshot()
    assert int(snapshot.get("ownership_leakage") or 0) == 0


def test_active_runtime_entrypoint_remains_mixed_plane() -> None:
    app_keys = _app_route_keys()

    assert ("GET", "/orders") in app_keys
    assert ("GET", "/marketplace/catalog") in app_keys
