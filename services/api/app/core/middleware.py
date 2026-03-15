from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import time
import uuid
from threading import Lock
from urllib.parse import parse_qsl, urlencode
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.auth import reset_current_claims, set_current_claims, verify_access_token
from app.core.permissions import effective_permissions_from_claims, is_permission_allowed, normalize_permission
from app.core.policy_matrix import AUTHENTICATED_ONLY, ROUTE_POLICY
from app.core.settings import get_settings
from app.core.perf_profile import end_request_profile, record_segment, start_request_profile
from app.db.models import License
from app.db.session import get_session_factory

try:
    import redis as redis_lib
except Exception:  # noqa: BLE001
    redis_lib = None




class RuntimeStats:
    def __init__(self) -> None:
        self._lock = Lock()
        self.started_at = datetime.now(timezone.utc)
        self._latencies_ms: deque[float] = deque(maxlen=2048)
        self._slow_request_ms = 1500.0

        self.in_flight = 0
        self.max_in_flight_seen = 0
        self.pending_waiters = 0
        self.max_pending_waiters_seen = 0

        self.total_started = 0
        self.total_completed = 0
        self.total_5xx = 0
        self.total_timeouts = 0
        self.total_rejected = 0
        self.total_queue_full_rejected = 0
        self.total_errors = 0
        self.total_slow = 0

        self.last_rejected_at: str | None = None
        self.last_timeout_at: str | None = None
        self.last_error_at: str | None = None

    def configure(self, *, latency_window_size: int, slow_request_ms: float) -> None:
        window = max(256, int(latency_window_size))
        slow_ms = max(100.0, float(slow_request_ms))
        with self._lock:
            if self._latencies_ms.maxlen != window:
                self._latencies_ms = deque(list(self._latencies_ms)[-window:], maxlen=window)
            self._slow_request_ms = slow_ms

    def try_enqueue_waiter(self, *, max_waiters: int) -> bool:
        cap = max(1, int(max_waiters))
        with self._lock:
            if self.pending_waiters >= cap:
                return False
            self.pending_waiters += 1
            if self.pending_waiters > self.max_pending_waiters_seen:
                self.max_pending_waiters_seen = self.pending_waiters
            return True

    def dequeue_waiter(self) -> int:
        with self._lock:
            self.pending_waiters = max(0, int(self.pending_waiters) - 1)
            return self.pending_waiters

    def current_pending_waiters(self) -> int:
        with self._lock:
            return int(self.pending_waiters)

    def on_acquire(self) -> int:
        with self._lock:
            self.total_started += 1
            self.in_flight += 1
            if self.in_flight > self.max_in_flight_seen:
                self.max_in_flight_seen = self.in_flight
            return self.in_flight

    def on_release(self) -> int:
        with self._lock:
            self.in_flight = max(0, int(self.in_flight) - 1)
            return self.in_flight

    def on_reject(self) -> None:
        with self._lock:
            self.total_rejected += 1
            self.last_rejected_at = datetime.now(timezone.utc).isoformat()

    def on_queue_full_reject(self) -> None:
        with self._lock:
            self.total_rejected += 1
            self.total_queue_full_rejected += 1
            self.last_rejected_at = datetime.now(timezone.utc).isoformat()

    def on_timeout(self) -> None:
        with self._lock:
            self.total_timeouts += 1
            self.last_timeout_at = datetime.now(timezone.utc).isoformat()

    def on_error(self) -> None:
        with self._lock:
            self.total_errors += 1
            self.last_error_at = datetime.now(timezone.utc).isoformat()

    def on_complete(self, *, status_code: int, duration_ms: float) -> None:
        d = max(0.0, float(duration_ms))
        with self._lock:
            self.total_completed += 1
            self._latencies_ms.append(d)
            if int(status_code) >= 500:
                self.total_5xx += 1
            if d >= self._slow_request_ms:
                self.total_slow += 1

    def _percentile(self, p: float) -> float:
        values = list(self._latencies_ms)
        if not values:
            return 0.0
        values.sort()
        if len(values) == 1:
            return float(values[0])
        idx = int(round((max(0.0, min(100.0, float(p))) / 100.0) * (len(values) - 1)))
        return float(values[idx])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                'started_at': self.started_at.isoformat(),
                'in_flight': int(self.in_flight),
                'max_in_flight_seen': int(self.max_in_flight_seen),
                'pending_waiters': int(self.pending_waiters),
                'max_pending_waiters_seen': int(self.max_pending_waiters_seen),
                'totals': {
                    'started': int(self.total_started),
                    'completed': int(self.total_completed),
                    'rejected': int(self.total_rejected),
                    'queue_full_rejected': int(self.total_queue_full_rejected),
                    'timeouts': int(self.total_timeouts),
                    'errors': int(self.total_errors),
                    'status_5xx': int(self.total_5xx),
                    'slow_requests': int(self.total_slow),
                },
                'latency_ms': {
                    'samples': int(len(self._latencies_ms)),
                    'p50': round(self._percentile(50), 2),
                    'p95': round(self._percentile(95), 2),
                    'p99': round(self._percentile(99), 2),
                    'slow_threshold_ms': round(float(self._slow_request_ms), 2),
                },
                'last': {
                    'rejected_at': self.last_rejected_at,
                    'timeout_at': self.last_timeout_at,
                    'error_at': self.last_error_at,
                },
            }


_RUNTIME_STATS = RuntimeStats()


def get_runtime_snapshot() -> dict[str, Any]:
    return _RUNTIME_STATS.snapshot()


class RuntimeProtectionMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        max_in_flight_requests: int = 300,
        queue_wait_timeout_ms: int = 90000,
        request_timeout_seconds: int = 120,
        max_queue_waiters: int = 2000,
        overload_retry_after_seconds: int = 1,
        latency_window_size: int = 2048,
        slow_request_ms: int = 1500,
        timing_headers_enabled: bool = False,
    ) -> None:
        super().__init__(app)
        self.max_in_flight_requests = max(1, int(max_in_flight_requests))
        self.queue_wait_timeout_seconds = max(0.001, float(queue_wait_timeout_ms) / 1000.0)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self.max_queue_waiters = max(1, int(max_queue_waiters))
        self.overload_retry_after_seconds = max(1, int(overload_retry_after_seconds))
        self.timing_headers_enabled = bool(timing_headers_enabled)

        self._semaphore = asyncio.Semaphore(self.max_in_flight_requests)
        _RUNTIME_STATS.configure(
            latency_window_size=max(256, int(latency_window_size)),
            slow_request_ms=max(100, int(slow_request_ms)),
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if str(request.url.path or '').startswith('/healthz'):
            return await call_next(request)

        if not _RUNTIME_STATS.try_enqueue_waiter(max_waiters=self.max_queue_waiters):
            _RUNTIME_STATS.on_queue_full_reject()
            resp = JSONResponse(status_code=503, content={'ok': False, 'detail': 'overloaded_queue_full'})
            resp.headers['Retry-After'] = str(self.overload_retry_after_seconds)
            return resp

        queue_started = time.perf_counter()
        acquired = False
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_wait_timeout_seconds)
            acquired = True
        except asyncio.TimeoutError:
            _RUNTIME_STATS.on_reject()
            resp = JSONResponse(status_code=503, content={'ok': False, 'detail': 'overloaded_retry'})
            resp.headers['Retry-After'] = str(self.overload_retry_after_seconds)
            return resp
        finally:
            _RUNTIME_STATS.dequeue_waiter()

        _RUNTIME_STATS.on_acquire()
        queue_wait_ms = (time.perf_counter() - queue_started) * 1000.0
        started = time.perf_counter()

        response = None
        status_code = 500
        try:
            response = await asyncio.wait_for(call_next(request), timeout=self.request_timeout_seconds)
            status_code = int(getattr(response, 'status_code', 500))
        except asyncio.TimeoutError:
            _RUNTIME_STATS.on_timeout()
            response = JSONResponse(status_code=504, content={'ok': False, 'detail': 'request_timeout'})
            status_code = 504
        except Exception:  # noqa: BLE001
            _RUNTIME_STATS.on_error()
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            _RUNTIME_STATS.on_complete(status_code=status_code, duration_ms=duration_ms)
            if acquired:
                self._semaphore.release()
            current = _RUNTIME_STATS.on_release()

            record_segment("queue_wait_ms", queue_wait_ms)
            record_segment("process_time_ms", duration_ms)

            if response is not None and self.timing_headers_enabled:
                response.headers['X-Process-Time-Ms'] = f'{duration_ms:.2f}'
                response.headers['X-Queue-Wait-Ms'] = f'{queue_wait_ms:.2f}'
                response.headers['X-In-Flight'] = str(current)
                response.headers['X-Queue-Depth'] = str(_RUNTIME_STATS.current_pending_waiters())

        return response

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings = get_settings()
        request_id = request.headers.get(settings.request_id_header) or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[settings.request_id_header] = request_id
        return response


class QueryGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_list_limit: int = 500) -> None:
        super().__init__(app)
        self.max_list_limit = max(10, int(max_list_limit))

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        raw_qs = request.scope.get("query_string", b"")
        if raw_qs and b"limit=" in raw_qs:
            parsed = parse_qsl(raw_qs.decode("utf-8", errors="ignore"), keep_blank_values=True)
            changed = False
            out: list[tuple[str, str]] = []

            for key, value in parsed:
                if key == "limit":
                    try:
                        n = int(value)
                        clamped = max(1, min(n, self.max_list_limit))
                        new_val = str(clamped)
                        if new_val != value:
                            changed = True
                        out.append((key, new_val))
                        continue
                    except Exception:  # noqa: BLE001
                        pass
                out.append((key, value))

            if changed:
                request.scope["query_string"] = urlencode(out, doseq=True).encode("utf-8")

        return await call_next(request)


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        claims = None
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            try:
                claims = verify_access_token(token)
            except Exception:  # noqa: BLE001
                claims = None

        ctx_token = set_current_claims(claims)
        request.state.claims = claims
        try:
            return await call_next(request)
        finally:
            reset_current_claims(ctx_token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


class SensitiveRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        max_requests_per_minute: int = 40,
        max_get_requests_per_minute: int = 600,
    ) -> None:
        super().__init__(app)
        self.max_requests_per_minute = max(1, int(max_requests_per_minute))
        self.max_get_requests_per_minute = max(0, int(max_get_requests_per_minute))
        self.window = timedelta(minutes=1)
        self.hits: dict[str, deque[datetime]] = defaultdict(deque)
        self.last_seen: dict[str, datetime] = {}
        self.max_tracked_keys = 200000
        self.key_ttl = timedelta(minutes=5)
        self.sensitive_prefixes = (
            "/auth/dev-token",
            "/guard/heartbeat",
            "/guard/device/lease",
            "/licenses/admin/",
            "/admin/public-profile/settings",
            "/admin/storage/",
            "/admin/incidents",
            "/superadmin/incidents",
            "/superadmin/storage",
            "/superadmin/security",
            "/ai/tenant-copilot",
            "/ai/superadmin-copilot",
            "/profile/",
            "/marketplace/",
            "/support/",
            "/iam/",
            "/admin/i18n/",
            "/superadmin/i18n/",
        )

        settings = get_settings()
        self.redis_key_prefix = str(settings.redis_key_prefix or "mydata").strip() or "mydata"
        self.redis_enabled = bool(settings.redis_rate_limit_enabled)
        self._redis = None

        if self.redis_enabled and redis_lib is not None:
            redis_url = str(settings.redis_url or "").strip()
            if redis_url:
                try:
                    self._redis = redis_lib.Redis.from_url(
                        redis_url,
                        decode_responses=True,
                        socket_connect_timeout=0.5,
                        socket_timeout=0.5,
                        health_check_interval=30,
                    )
                except Exception:  # noqa: BLE001
                    self._redis = None

    def _resolve_limit(self, method: str) -> int:
        m = str(method or "").strip().upper()
        if m in ("GET", "HEAD", "OPTIONS"):
            return int(self.max_get_requests_per_minute)
        return int(self.max_requests_per_minute)

    def _cleanup_if_needed(self, now: datetime) -> None:
        if len(self.last_seen) <= self.max_tracked_keys:
            return

        stale_cutoff = now - self.key_ttl
        stale_keys = [k for k, ts in self.last_seen.items() if ts < stale_cutoff]
        if not stale_keys:
            stale_keys = [k for k, _ in sorted(self.last_seen.items(), key=lambda item: item[1])[:5000]]
        else:
            stale_keys = stale_keys[:5000]

        for key in stale_keys:
            self.last_seen.pop(key, None)
            self.hits.pop(key, None)

    def _try_redis_limit(self, *, ip: str, method: str, path: str, now: datetime, limit: int) -> bool | None:
        if self._redis is None:
            return None

        bucket = int(now.timestamp() // 60)
        key = f"{self.redis_key_prefix}:rl:{bucket}:{ip}:{method}:{path}"
        try:
            current = int(self._redis.incr(key))
            if current == 1:
                self._redis.expire(key, 120)
            return current <= limit
        except Exception:  # noqa: BLE001
            return None

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if any(path.startswith(p) for p in self.sensitive_prefixes):
            limit = self._resolve_limit(request.method)
            if limit > 0:
                now = datetime.now(timezone.utc)
                ip = request.client.host if request.client else "unknown"
                method = str(request.method or "GET").upper()

                redis_allowed = self._try_redis_limit(ip=ip, method=method, path=path, now=now, limit=limit)
                if redis_allowed is False:
                    return JSONResponse(status_code=429, content={"ok": False, "detail": "rate_limited"})

                if redis_allowed is None:
                    self._cleanup_if_needed(now)
                    key = f"{ip}:{method}:{path}"
                    q = self.hits[key]
                    cutoff = now - self.window
                    while q and q[0] < cutoff:
                        q.popleft()

                    if len(q) >= limit:
                        return JSONResponse(status_code=429, content={"ok": False, "detail": "rate_limited"})

                    q.append(now)
                    self.last_seen[key] = now

        return await call_next(request)


class CoreEntitlementMiddleware(BaseHTTPMiddleware):
    """
    Strict core-license enforcement on tenant-protected routes.
    SUPERADMIN bypass is allowed.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self.protected_prefixes = (
            "/guard/",
            "/admin/public-profile/",
            "/admin/storage/",
            "/admin/incidents",
            "/superadmin/incidents",
            "/superadmin/storage",
            "/superadmin/security",
            "/ai/tenant-copilot",
            "/profile/",
            "/marketplace/",
            "/support/",
            "/iam/",
            "/admin/i18n/",
        )
        self.excluded_prefixes = (
            "/healthz",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/auth/",
            "/public/",
            "/licenses/admin/issue-startup",
            "/admin/tenants/bootstrap-demo",
            "/i18n/locales",
            "/i18n/catalog/",
        )
        settings = get_settings()
        self.cache_ttl_seconds = max(1, int(settings.core_entitlement_cache_ttl_seconds))
        self.cache_max_entries = max(100, int(settings.core_entitlement_cache_max_entries))
        # tenant_id -> (expires_monotonic, has_core)
        self._core_cache: dict[str, tuple[float, bool]] = {}

    def _is_protected(self, path: str) -> bool:
        if any(path.startswith(x) for x in self.excluded_prefixes):
            return False
        return any(path.startswith(x) for x in self.protected_prefixes)

    def _cache_get(self, tenant_id: str, now_mono: float) -> bool | None:
        entry = self._core_cache.get(tenant_id)
        if entry is None:
            return None
        expires_at, has_core = entry
        if expires_at <= now_mono:
            self._core_cache.pop(tenant_id, None)
            return None
        return has_core

    def _cache_set(self, tenant_id: str, has_core: bool, now_mono: float) -> None:
        if tenant_id in self._core_cache:
            self._core_cache.pop(tenant_id, None)
        self._core_cache[tenant_id] = (now_mono + float(self.cache_ttl_seconds), bool(has_core))
        while len(self._core_cache) > self.cache_max_entries:
            oldest_key = next(iter(self._core_cache))
            self._core_cache.pop(oldest_key, None)

    def _required_permission_for_request(self, *, method: str, path: str, claims: dict[str, Any]) -> str | None:
        # Fast early-deny: avoid DB entitlement lookup when policy permission is already missing.
        rule = ROUTE_POLICY.get((method, path))
        if rule is None:
            return None

        required = normalize_permission(rule.permission_code)
        if not required or required == AUTHENTICATED_ONLY:
            return None

        effective = effective_permissions_from_claims(claims)
        if is_permission_allowed(required, effective):
            return None
        return required

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = str(getattr(request.state, "request_id", "") or "")
        if not request_id:
            header_name = str(get_settings().request_id_header or "X-Request-ID").strip() or "X-Request-ID"
            request_id = str(request.headers.get(header_name) or "").strip()

        profile_token = start_request_profile(
            method=str(request.method or "GET"),
            path=str(request.url.path or ""),
            request_id=request_id or None,
        )

        middleware_started = time.perf_counter()
        status_code = 500
        response = None
        try:
            path = request.url.path
            if not self._is_protected(path):
                response = await call_next(request)
                status_code = int(getattr(response, "status_code", 500))
                return response

            auth = request.headers.get("Authorization")
            if not auth or not auth.lower().startswith("bearer "):
                response = JSONResponse(status_code=401, content={"ok": False, "detail": "missing_authorization"})
                status_code = 401
                return response

            token = auth.split(" ", 1)[1].strip()
            try:
                claims = verify_access_token(token)
            except Exception as exc:  # noqa: BLE001
                response = JSONResponse(status_code=401, content={"ok": False, "detail": str(exc)})
                status_code = 401
                return response

            roles = set(claims.get("roles") or [])
            if "SUPERADMIN" in roles:
                response = await call_next(request)
                status_code = int(getattr(response, "status_code", 500))
                return response

            tenant_id = str(claims.get("tenant_id") or "").strip()
            if not tenant_id:
                response = JSONResponse(status_code=403, content={"ok": False, "detail": "missing_tenant_context"})
                status_code = 403
                return response

            method = str(request.method or "GET").upper()
            required = self._required_permission_for_request(method=method, path=path, claims=claims)
            if required:
                response = JSONResponse(status_code=403, content={"ok": False, "detail": f"permission_required:{required}"})
                status_code = 403
                return response

            now_mono = time.monotonic()
            has_core = self._cache_get(tenant_id, now_mono)

            if has_core is None:
                now = datetime.now(timezone.utc)
                db = get_session_factory()()
                try:
                    core = (
                        db.query(License)
                        .filter(
                            License.tenant_id == tenant_id,
                            License.license_type == "CORE",
                            License.status == "ACTIVE",
                            License.valid_from <= now,
                            License.valid_to >= now,
                        )
                        .first()
                    )
                    has_core = core is not None
                finally:
                    db.close()
                self._cache_set(tenant_id, has_core, now_mono)

            if not has_core:
                response = JSONResponse(status_code=402, content={"ok": False, "detail": "core_license_required"})
                status_code = 402
                return response

            response = await call_next(request)
            status_code = int(getattr(response, "status_code", 500))
            return response
        finally:
            total_ms = (time.perf_counter() - middleware_started) * 1000.0
            record_segment("middleware_total_ms", total_ms)
            record_segment("total_request_ms", total_ms)
            end_request_profile(status_code=status_code, token=profile_token)


