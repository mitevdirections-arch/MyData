from __future__ import annotations

from fastapi import FastAPI

from app.launcher.foundation import create_foundation_router


def create_canary_foundation_app() -> FastAPI:
    app = FastAPI(
        title="MyData Foundation Canary",
        version="0.5.0-canary",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.include_router(create_foundation_router())
    return app


app = create_canary_foundation_app()
