from __future__ import annotations

from fastapi import FastAPI

from app.launcher.operational import create_operational_router


def create_canary_operational_app() -> FastAPI:
    app = FastAPI(
        title="MyData Operational Canary",
        version="0.5.0-canary",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(create_operational_router())
    return app


app = create_canary_operational_app()
