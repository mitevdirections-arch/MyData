from __future__ import annotations

from fastapi import APIRouter

from app.core.route_ownership import ROUTE_PLANE_OPERATIONAL
from app.launcher.composition import compose_plane_router


def create_operational_router() -> APIRouter:
    return compose_plane_router(ROUTE_PLANE_OPERATIONAL)
