from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.middleware import (
    AuthContextMiddleware,
    CoreEntitlementMiddleware,
    QueryGuardMiddleware,
    RequestContextMiddleware,
    RuntimeProtectionMiddleware,
    SecurityHeadersMiddleware,
    SensitiveRateLimitMiddleware,
    get_runtime_snapshot,
)
from app.core.perf_profile import get_perf_snapshot, reset_perf_snapshot
from app.core.rls import RLSScopeViolationError
from app.core.settings import get_settings
from app.core.startup_security import enforce_startup_security, is_prod_env
from app.db.session import get_engine
from app.router import api_router


startup_logger = logging.getLogger("mydata.startup")


def _database_health_payload() -> tuple[int, dict[str, Any]]:
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return 200, {"ok": True, "db": "ok", "detail": "db_ready"}
    except RuntimeError as exc:
        msg = str(exc or "")
        detail = "database_url_missing" if "DATABASE_URL is required" in msg else "database_runtime_error"
        return 503, {"ok": False, "db": "fail", "detail": detail, "error": msg}
    except Exception as exc:  # noqa: BLE001
        detail = "db_connect_failed"
        try:
            from sqlalchemy.exc import ArgumentError

            if isinstance(exc, ArgumentError):
                detail = "database_url_invalid"
        except Exception:  # noqa: BLE001
            pass

        return 503, {"ok": False, "db": "fail", "detail": detail, "error": str(exc)}


def create_app() -> FastAPI:
    settings = get_settings()
    enforce_startup_security(settings)

    in_prod = is_prod_env(settings.app_env)
    docs_enabled = not in_prod or bool(settings.api_docs_enabled_in_prod)

    app = FastAPI(
        title="MyData API",
        version="0.5.0",
        docs_url=("/docs" if docs_enabled else None),
        redoc_url=("/redoc" if docs_enabled else None),
        openapi_url=("/openapi.json" if docs_enabled else None),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=bool(settings.cors_allow_credentials),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        RuntimeProtectionMiddleware,
        max_in_flight_requests=settings.api_max_in_flight_requests,
        queue_wait_timeout_ms=settings.api_queue_wait_timeout_ms,
        request_timeout_seconds=settings.api_request_timeout_seconds,
        max_queue_waiters=settings.api_max_queue_waiters,
        overload_retry_after_seconds=settings.api_overload_retry_after_seconds,
        latency_window_size=settings.api_runtime_metrics_window_size,
        slow_request_ms=settings.api_runtime_slow_request_ms,
        timing_headers_enabled=settings.api_runtime_timing_headers_enabled,
    )
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        SensitiveRateLimitMiddleware,
        max_requests_per_minute=settings.sensitive_rate_limit_per_minute,
        max_get_requests_per_minute=settings.sensitive_get_rate_limit_per_minute,
    )
    app.add_middleware(
        QueryGuardMiddleware,
        max_list_limit=settings.api_list_limit_max,
    )
    app.add_middleware(CoreEntitlementMiddleware)

    @app.exception_handler(RLSScopeViolationError)
    async def _rls_scope_violation(_request, exc: RLSScopeViolationError):
        return JSONResponse(status_code=403, content={"ok": False, "detail": str(exc) or "rls_tenant_scope_violation"})

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, bool]:
        return {"ok": True}


    @app.get("/healthz/runtime", tags=["system"])
    def healthz_runtime() -> dict[str, object]:
        return {"ok": True, "runtime": get_runtime_snapshot()}

    @app.get("/healthz/perf", tags=["system"])
    def healthz_perf() -> dict[str, object]:
        return {"ok": True, "profiling": get_perf_snapshot()}

    @app.post("/healthz/perf/reset", tags=["system"])
    def healthz_perf_reset() -> dict[str, object]:
        reset_perf_snapshot()
        return {"ok": True, "reset": True, "profiling": get_perf_snapshot()}

    @app.get("/healthz/db", tags=["system"])
    def healthz_db():
        status, payload = _database_health_payload()
        if status == 200:
            return payload
        return JSONResponse(status_code=status, content=payload)

    @app.get("/readyz", tags=["system"])
    def readyz():
        status, db_payload = _database_health_payload()
        ready = bool(status == 200 and db_payload.get("ok") is True)
        payload: dict[str, Any] = {
            "ok": ready,
            "ready": ready,
            "checks": {
                "db": db_payload,
            },
        }
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    app.include_router(api_router)

    async def _startup_routes_dump() -> None:
        if not bool(settings.api_startup_routes_print_enabled):
            return

        from fastapi.routing import APIRoute

        rows: list[tuple[str, str, str]] = []
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            methods = sorted(set(route.methods or set()))
            methods = [m for m in methods if m not in {"HEAD", "OPTIONS"}]
            if not methods:
                continue
            tags = ",".join(route.tags or [])
            for method in methods:
                rows.append((method, route.path, tags))

        rows.sort(key=lambda x: (x[1], x[0]))
        total = len(rows)
        max_rows = max(1, int(settings.api_startup_routes_print_max))
        shown = rows[:max_rows]

        startup_logger.info("startup_routes_loaded total=%s shown=%s", total, len(shown))
        for method, path, tags in shown:
            if tags:
                startup_logger.info("route %s %s tags=%s", method, path, tags)
            else:
                startup_logger.info("route %s %s", method, path)

        if total > len(shown):
            startup_logger.info("startup_routes_truncated omitted=%s", total - len(shown))

    app.add_event_handler("startup", _startup_routes_dump)

    return app


app = create_app()