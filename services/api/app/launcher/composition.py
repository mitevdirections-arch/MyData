from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.core.route_ownership import (
    ROUTE_PLANE_FOUNDATION,
    ROUTE_PLANE_OPERATIONAL,
    ROUTE_PLANE_OWNERSHIP,
    route_keys_without_explicit_plane_ownership,
    route_plane_ownership_drift,
    resolve_route_plane,
)
from app.router import api_router


_ALLOWED_PLANES = {ROUTE_PLANE_FOUNDATION, ROUTE_PLANE_OPERATIONAL}


def _normalize_plane(plane: str) -> str:
    raw = str(plane or "").strip().upper()
    if raw not in _ALLOWED_PLANES:
        raise ValueError("plane_invalid")
    return raw


def _route_methods(route: APIRoute) -> list[str]:
    methods = sorted(set(route.methods or set()))
    return [m for m in methods if m not in {"HEAD", "OPTIONS"}]


def route_keys_from_router(router: APIRouter) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in _route_methods(route):
            out.add((method, route.path))
    return out


def plane_owned_route_keys(plane: str) -> set[tuple[str, str]]:
    norm = _normalize_plane(plane)
    return {(method, path) for (method, path), owner in ROUTE_PLANE_OWNERSHIP.items() if owner == norm}


def compose_plane_router(plane: str) -> APIRouter:
    norm = _normalize_plane(plane)

    missing = route_keys_without_explicit_plane_ownership()
    drift = route_plane_ownership_drift()
    if missing or drift.get("missing") or drift.get("extra"):
        raise RuntimeError("route_ownership_contract_incomplete")

    target = APIRouter(dependencies=list(api_router.dependencies or []))

    for route in api_router.routes:
        if not isinstance(route, APIRoute):
            continue

        selected_methods = [m for m in _route_methods(route) if resolve_route_plane(m, route.path) == norm]
        if not selected_methods:
            continue

        target.add_api_route(
            route.path,
            route.endpoint,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=list(route.tags or []),
            dependencies=list(route.dependencies or []),
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=dict(route.responses or {}),
            deprecated=route.deprecated,
            methods=selected_methods,
            operation_id=route.operation_id,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            name=route.name,
            callbacks=route.callbacks,
            openapi_extra=route.openapi_extra,
            generate_unique_id_function=route.generate_unique_id_function,
        )

    expected = plane_owned_route_keys(norm)
    actual = route_keys_from_router(target).intersection(set(ROUTE_PLANE_OWNERSHIP.keys()))
    if actual != expected:
        raise RuntimeError("launcher_plane_composition_drift")

    return target


def launcher_composition_snapshot() -> dict[str, Any]:
    foundation_keys = plane_owned_route_keys(ROUTE_PLANE_FOUNDATION)
    operational_keys = plane_owned_route_keys(ROUTE_PLANE_OPERATIONAL)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "foundation_routes": len(foundation_keys),
        "operational_routes": len(operational_keys),
        "ownership_leakage": len(foundation_keys.intersection(operational_keys)),
    }
