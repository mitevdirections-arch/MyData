import pytest
from fastapi.routing import APIRoute

from app.main import app


@pytest.fixture(scope="session")
def registered_paths() -> set[str]:
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
    }
