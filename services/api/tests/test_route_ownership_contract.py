from __future__ import annotations

from app.core.policy_matrix import ROUTE_POLICY, is_protected_route_path
from app.core.route_ownership import (
    ROUTE_PLANE_FOUNDATION,
    ROUTE_PLANE_OPERATIONAL,
    route_keys_without_explicit_plane_ownership,
    route_plane_ownership_drift,
    resolve_route_plane,
)
from app.main import app


def test_route_ownership_contract_covers_all_protected_routes() -> None:
    missing: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if not path:
            continue
        if "HEAD" in methods and "GET" in methods:
            methods.remove("HEAD")
        for method in sorted(methods):
            if not is_protected_route_path(path):
                continue
            key = (method, path)
            if key not in ROUTE_POLICY:
                continue
            if resolve_route_plane(method, path) is None:
                missing.append(f"{method} {path}")

    assert missing == []


def test_route_ownership_contract_has_no_missing_or_drift() -> None:
    assert route_keys_without_explicit_plane_ownership() == []
    drift = route_plane_ownership_drift()
    assert drift.get("missing") == []
    assert drift.get("extra") == []


def test_orders_routes_are_operational() -> None:
    for method, path in sorted(ROUTE_POLICY.keys()):
        if path == "/orders" or path.startswith("/orders/"):
            assert resolve_route_plane(method, path) == ROUTE_PLANE_OPERATIONAL


def test_marketplace_routes_are_foundation_controlled_facade() -> None:
    for method, path in sorted(ROUTE_POLICY.keys()):
        if path == "/marketplace" or path.startswith("/marketplace/"):
            assert resolve_route_plane(method, path) == ROUTE_PLANE_FOUNDATION


def test_partners_routes_are_operational() -> None:
    for method, path in sorted(ROUTE_POLICY.keys()):
        if path == "/partners" or path.startswith("/partners/"):
            assert resolve_route_plane(method, path) == ROUTE_PLANE_OPERATIONAL
