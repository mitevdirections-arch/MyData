from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

_BASE_DIR = Path(__file__).resolve().parents[2]

_TLS = threading.local()

PERF_SEGMENT_KEYS = [
    "token_verify_ms",
    "policy_resolve_ms",
    "authz_ms",
    "tenant_db_authz_ms",
    "tenant_db_authz_sql_ms",
    "tenant_db_authz_db_checkout_ms",
    "tenant_db_authz_exec_ms",
    "tenant_db_authz_materialize_ms",
    "tenant_db_authz_shape_ms",
    "tenant_db_authz_wrapper_ms",
    "tenant_db_authz_session_ms",
    "tenant_db_authz_fastpath_call_ms",
    "sql_query_count_tenant_db_authz",
    "sql_query_ms_tenant_db_authz",
    "authz_fast_path_shadow_compares",
    "authz_fast_path_shadow_mismatches",
    "authz_fast_path_hits",
    "authz_fast_path_fallbacks",
    "entitlement_ms",
    "entitlement_sql_ms",
    "entitlement_session_ms",
    "entitlement_wrapper_ms",
    "entitlement_decision_ms",
    "sql_query_count_entitlement",
    "sql_query_ms_entitlement",
    "iam_user_sql_query_count",
    "iam_user_sql_query_ms",
    "iam_roles_sql_query_count",
    "iam_roles_sql_query_ms",
    "iam_entitlement_sql_query_count",
    "iam_entitlement_sql_query_ms",
    "iam_user_phase_ms",
    "iam_roles_phase_ms",
    "iam_entitlement_phase_ms",
    "access_envelope_total_ms",
    "access_duplicate_work_count",
    "access_duplicate_work_ms",
    "sql_query_count",
    "sql_query_ms",
    "query_ms",
    "serialize_ms",
    "total_service_ms",
    "orders_query_ms",
    "orders_materialize_ms",
    "orders_serialize_ms",
    "orders_service_ms",
    "orders_extra_sql_count",
    "orders_extra_sql_ms",
    "protected_envelope_total_ms",
    "protected_token_verify_ms",
    "protected_claims_prepare_ms",
    "protected_policy_ms",
    "protected_session_acquire_ms",
    "middleware_total_ms",
    "request_wall_ms",
]

MODE_BASELINE_NO_TRACE = "baseline_no_trace"
MODE_DIAGNOSTIC_TRACE = "diagnostic_trace"
SUPPORTED_MODES = {MODE_BASELINE_NO_TRACE, MODE_DIAGNOSTIC_TRACE}
ENTITLEMENT_QUERY_MODE_ENV = "MYDATA_PERF_ENTITLEMENT_QUERY_MODE"
COOLDOWN_STATE_FILE = _BASE_DIR / "docs" / "perf" / ".orders_db_backed_baseline_state.json"

MODE_DEFAULTS: dict[str, dict[str, Any]] = {
    MODE_BASELINE_NO_TRACE: {
        "workers": 12,
        "requests_per_run": 180,
        "runs": 3,
        "warmup_requests": 12,
        "cooldown_seconds": 65,
        "require_profiling_enabled": False,
        "forbid_profiling_enabled": True,
        "expect_sql_trace": False,
    },
    MODE_DIAGNOSTIC_TRACE: {
        "workers": 12,
        "requests_per_run": 180,
        "runs": 3,
        "warmup_requests": 12,
        "cooldown_seconds": 0,
        "require_profiling_enabled": True,
        "forbid_profiling_enabled": False,
        "expect_sql_trace": True,
    },
}


class PerfBaselineError(RuntimeError):
    pass


def _resolve_entitlement_query_mode() -> str:
    mode = str(os.getenv(ENTITLEMENT_QUERY_MODE_ENV, "legacy")).strip().lower()
    if mode == "core":
        return "core"
    return "legacy"


def _read_cooldown_state() -> dict[str, Any]:
    if not COOLDOWN_STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(COOLDOWN_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_cooldown_state(payload: dict[str, Any]) -> None:
    COOLDOWN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN_STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_iso_utc(raw: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _apply_cooldown_guard(*, mode: str, cooldown_seconds: int) -> dict[str, Any]:
    if str(mode) != MODE_BASELINE_NO_TRACE:
        return {
            "mode": str(mode),
            "cooldown_seconds": int(max(0, int(cooldown_seconds))),
            "applied": False,
            "waited_seconds": 0.0,
            "state_file": str(COOLDOWN_STATE_FILE),
            "reason": "not_baseline_mode",
        }

    cooldown = max(0, int(cooldown_seconds))
    if cooldown <= 0:
        return {
            "mode": str(mode),
            "cooldown_seconds": 0,
            "applied": False,
            "waited_seconds": 0.0,
            "state_file": str(COOLDOWN_STATE_FILE),
            "reason": "cooldown_disabled",
        }

    state = _read_cooldown_state()
    last_started_raw = str(state.get("last_baseline_invocation_started_at_utc") or "").strip()
    now = datetime.now(timezone.utc)
    waited_seconds = 0.0
    since_last_seconds = None

    if last_started_raw:
        last_started = _parse_iso_utc(last_started_raw)
        if last_started is not None:
            since_last_seconds = max(0.0, (now - last_started).total_seconds())
            remaining = float(cooldown) - since_last_seconds
            if remaining > 0:
                time.sleep(remaining)
                waited_seconds = remaining
                now = datetime.now(timezone.utc)
                since_last_seconds = max(0.0, (now - last_started).total_seconds())

    invocation_started = now.isoformat()
    _write_cooldown_state(
        {
            "last_baseline_invocation_started_at_utc": invocation_started,
            "last_mode": str(mode),
            "cooldown_seconds": int(cooldown),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return {
        "mode": str(mode),
        "cooldown_seconds": int(cooldown),
        "applied": True,
        "waited_seconds": round(float(waited_seconds), 3),
        "since_last_baseline_seconds": round(float(since_last_seconds), 3) if since_last_seconds is not None else None,
        "state_file": str(COOLDOWN_STATE_FILE),
        "reason": "baseline_cooldown_guard",
    }


def _auth_header(token: str | None) -> str | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        return raw
    return f"Bearer {raw}"


def _get_thread_opener() -> urllib.request.OpenerDirector:
    opener = getattr(_TLS, "opener", None)
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.HTTPHandler())
        setattr(_TLS, "opener", opener)
    return opener


def _open(req: urllib.request.Request, *, timeout_seconds: float):
    opener = _get_thread_opener()
    return opener.open(req, timeout=timeout_seconds)  # noqa: S310


def _json_request(
    *,
    method: str,
    url: str,
    auth: str | None,
    timeout_seconds: float,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | None, dict[str, str]]:
    body = None
    req = urllib.request.Request(url=url, method=str(method).upper())
    req.add_header("Connection", "keep-alive")
    req.add_header("Accept", "application/json")
    if auth:
        req.add_header("Authorization", auth)
    if extra_headers:
        for key, value in extra_headers.items():
            req.add_header(str(key), str(value))
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = body

    try:
        with _open(req, timeout_seconds=timeout_seconds) as resp:
            status = int(resp.getcode())
            text = resp.read().decode("utf-8")
            parsed = None
            if text:
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        parsed = obj
                except Exception:
                    parsed = None
            headers = {str(k): str(v) for k, v in dict(resp.headers).items()}
            return status, parsed, headers
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        text = ""
        try:
            text = exc.read().decode("utf-8")
        except Exception:
            text = ""
        parsed = None
        if text:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    parsed = obj
            except Exception:
                parsed = None
        headers = {str(k): str(v) for k, v in dict(getattr(exc, "headers", {}) or {}).items()}
        return status, parsed, headers


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    q = statistics.quantiles(values, n=100)
    idx = max(0, min(99, int(p) - 1))
    return float(q[idx])


def _request_once(
    *,
    api_base: str,
    path: str,
    auth: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = f"{str(api_base).rstrip('/')}{path}"
    req = urllib.request.Request(url=url, method="GET")
    req.add_header("Connection", "keep-alive")
    req.add_header("Authorization", auth)

    started = time.perf_counter()
    try:
        with _open(req, timeout_seconds=timeout_seconds) as resp:
            _ = resp.read(128)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status = int(resp.getcode())
            process_raw = str(resp.headers.get("X-Process-Time-Ms") or "").strip()
            queue_raw = str(resp.headers.get("X-Queue-Wait-Ms") or "").strip()
            process_ms = float(process_raw) if process_raw else None
            queue_ms = float(queue_raw) if queue_raw else None
            return {
                "ok": 200 <= status < 300,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "error": None,
                "error_detail": None,
                "timeout": False,
                "process_ms": process_ms,
                "queue_ms": queue_ms,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status = int(getattr(exc, "code", 0) or 0)
        text = ""
        body_obj: dict[str, Any] | None = None
        try:
            text = exc.read().decode("utf-8")
        except Exception:
            text = ""
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    body_obj = parsed
            except Exception:
                body_obj = None
        detail = ""
        if isinstance(body_obj, dict):
            raw_detail = body_obj.get("detail")
            if raw_detail is not None:
                detail = str(raw_detail)
            elif body_obj.get("error") is not None:
                detail = str(body_obj.get("error"))
        if not detail and text:
            detail = str(text).strip().replace("\r", " ").replace("\n", " ")[:240]
        return {
            "ok": False,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "error": f"http_error:{status}",
            "error_detail": detail or None,
            "timeout": False,
            "process_ms": None,
            "queue_ms": None,
        }
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        reason = str(getattr(exc, "reason", "url_error"))
        timeout_like = "timed out" in reason.lower() or "timeout" in reason.lower()
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"network_error:{reason}",
            "error_detail": reason,
            "timeout": bool(timeout_like),
            "process_ms": None,
            "queue_ms": None,
        }
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": "timeout",
            "error_detail": "timeout",
            "timeout": True,
            "process_ms": None,
            "queue_ms": None,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"exception:{exc}",
            "error_detail": str(exc),
            "timeout": False,
            "process_ms": None,
            "queue_ms": None,
        }


def _run_load(
    *,
    api_base: str,
    path: str,
    auth: str,
    workers: int,
    total_requests: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    requests_count = max(1, int(total_requests))
    workers_count = max(1, int(workers))

    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers_count) as pool:
        futures = [
            pool.submit(
                _request_once,
                api_base=api_base,
                path=path,
                auth=auth,
                timeout_seconds=timeout_seconds,
            )
            for _ in range(requests_count)
        ]
        for fut in as_completed(futures):
            rows.append(fut.result())

    duration_seconds = max(0.001, time.perf_counter() - started)
    latencies = [float(x.get("elapsed_ms") or 0.0) for x in rows]

    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    error_detail_counts: dict[tuple[str, str], int] = {}
    ok_count = 0
    for row in rows:
        status_key = str(int(row.get("status") or 0))
        status_counts[status_key] = int(status_counts.get(status_key, 0)) + 1
        if bool(row.get("ok")):
            ok_count += 1
        err = str(row.get("error") or "").strip()
        if err:
            error_counts[err] = int(error_counts.get(err, 0)) + 1
            detail = str(row.get("error_detail") or "").strip()
            if detail:
                detail_key = (err, detail)
                error_detail_counts[detail_key] = int(error_detail_counts.get(detail_key, 0)) + 1

    process_vals = [float(x["process_ms"]) for x in rows if isinstance(x.get("process_ms"), (int, float))]
    queue_vals = [float(x["queue_ms"]) for x in rows if isinstance(x.get("queue_ms"), (int, float))]

    return {
        "requests": int(requests_count),
        "workers": int(workers_count),
        "duration_seconds": round(duration_seconds, 3),
        "throughput_rps": round(float(requests_count) / duration_seconds, 2),
        "p50_ms": round(_percentile(latencies, 50), 2),
        "p95_ms": round(_percentile(latencies, 95), 2),
        "avg_ms": round(float(sum(latencies) / max(1, len(latencies))), 2),
        "status_counts": status_counts,
        "ok_2xx": int(ok_count),
        "non_2xx": int(requests_count - ok_count),
        "timing_headers": {
            "process_ms_avg": round(float(sum(process_vals) / max(1, len(process_vals))), 3) if process_vals else None,
            "process_ms_p95": round(_percentile(process_vals, 95), 3) if process_vals else None,
            "queue_wait_ms_avg": round(float(sum(queue_vals) / max(1, len(queue_vals))), 3) if queue_vals else None,
            "queue_wait_ms_p95": round(_percentile(queue_vals, 95), 3) if queue_vals else None,
        },
        "top_errors": [
            {"error": key, "count": value}
            for key, value in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ],
        "top_error_details": [
            {"error": key[0], "detail": key[1], "count": value}
            for key, value in sorted(error_detail_counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:8]
        ],
    }


def _reset_perf_snapshot(*, api_base: str, timeout_seconds: float) -> None:
    status, body, _headers = _json_request(
        method="POST",
        url=f"{str(api_base).rstrip('/')}/healthz/perf/reset",
        auth=None,
        timeout_seconds=timeout_seconds,
        payload={},
    )
    if status != 200:
        raise PerfBaselineError(f"perf_reset_failed:{status}:{(body or {}).get('detail')}")


def _get_perf_snapshot(*, api_base: str, timeout_seconds: float) -> dict[str, Any]:
    status, body, _headers = _json_request(
        method="GET",
        url=f"{str(api_base).rstrip('/')}/healthz/perf",
        auth=None,
        timeout_seconds=timeout_seconds,
        payload=None,
    )
    if status != 200:
        raise PerfBaselineError(f"perf_snapshot_failed:{status}:{(body or {}).get('detail')}")

    profiling = (body or {}).get("profiling") if isinstance(body, dict) else None
    if not isinstance(profiling, dict):
        return {"enabled": False, "segments": {}, "status_counts": {}, "total_requests": 0}

    raw_segments = profiling.get("segments")
    segments_obj = raw_segments if isinstance(raw_segments, dict) else {}
    selected_segments: dict[str, Any] = {}
    for key in PERF_SEGMENT_KEYS:
        value = segments_obj.get(key)
        if isinstance(value, dict):
            selected_segments[key] = {
                "count": int(value.get("count") or 0),
                "avg_ms": value.get("avg_ms"),
                "p50_ms": value.get("p50_ms"),
                "p95_ms": value.get("p95_ms"),
                "p99_ms": value.get("p99_ms"),
                "max_ms": value.get("max_ms"),
            }

    return {
        "enabled": bool(profiling.get("enabled")),
        "total_requests": int(profiling.get("total_requests") or 0),
        "status_counts": profiling.get("status_counts") if isinstance(profiling.get("status_counts"), dict) else {},
        "segments": selected_segments,
    }


def _wait_for_runtime_ready(
    *,
    api_base: str,
    timeout_seconds: float,
    max_wait_seconds: float,
    poll_seconds: float,
    stable_checks: int,
) -> dict[str, Any]:
    deadline = time.perf_counter() + max(1.0, float(max_wait_seconds))
    poll = max(0.2, float(poll_seconds))
    need_stable = max(1, int(stable_checks))
    consecutive = 0
    attempts = 0
    last_health_status = 0
    last_ready_status = 0
    last_ready_detail = ""

    while time.perf_counter() <= deadline:
        attempts += 1

        hs, hb, _ = _json_request(
            method="GET",
            url=f"{str(api_base).rstrip('/')}/healthz",
            auth=None,
            timeout_seconds=timeout_seconds,
            payload=None,
        )
        rs, rb, _ = _json_request(
            method="GET",
            url=f"{str(api_base).rstrip('/')}/readyz",
            auth=None,
            timeout_seconds=timeout_seconds,
            payload=None,
        )

        last_health_status = int(hs)
        last_ready_status = int(rs)
        ready_ok = bool(isinstance(rb, dict) and rb.get("ok") is True and rb.get("ready") is True)
        health_ok = bool(isinstance(hb, dict) and hb.get("ok") is True)
        if isinstance(rb, dict):
            last_ready_detail = str(rb.get("detail") or rb.get("error") or "").strip()

        if int(hs) == 200 and int(rs) == 200 and health_ok and ready_ok:
            consecutive += 1
            if consecutive >= need_stable:
                return {
                    "attempts": int(attempts),
                    "stable_checks": int(need_stable),
                    "health_status": int(hs),
                    "ready_status": int(rs),
                    "ready_detail": last_ready_detail or None,
                }
        else:
            consecutive = 0

        time.sleep(poll)

    raise PerfBaselineError(
        "runtime_readiness_timeout:"
        f"health_status={last_health_status}:ready_status={last_ready_status}:ready_detail={last_ready_detail}"
    )


def _validate_profiling_mode(
    *,
    profiling: dict[str, Any],
    require_enabled: bool,
    forbid_enabled: bool,
) -> None:
    enabled = bool(profiling.get("enabled"))
    if require_enabled and not enabled:
        raise PerfBaselineError("run_invalid_profiling_expected_on")
    if forbid_enabled and enabled:
        raise PerfBaselineError("run_invalid_profiling_expected_off")


def _snapshot_has_sql_trace(perf_snapshot: dict[str, Any]) -> bool:
    segments = perf_snapshot.get("segments")
    if not isinstance(segments, dict):
        return False
    sql_count = segments.get("sql_query_count")
    if isinstance(sql_count, dict) and float(sql_count.get("count") or 0) > 0:
        return True
    for key, value in segments.items():
        if str(key).startswith("sql_query_count_") and isinstance(value, dict) and float(value.get("count") or 0) > 0:
            return True
    return False


def _validate_sql_trace_across_results(*, endpoint_results: list[dict[str, Any]], expect_sql_trace: bool) -> None:
    observed_any = False
    for endpoint in endpoint_results:
        runs = endpoint.get("runs") if isinstance(endpoint, dict) else None
        if not isinstance(runs, list):
            continue
        for row in runs:
            snapshot = row.get("perf_snapshot") if isinstance(row, dict) else None
            if isinstance(snapshot, dict) and _snapshot_has_sql_trace(snapshot):
                observed_any = True
                break
        if observed_any:
            break

    if expect_sql_trace and not observed_any:
        raise PerfBaselineError("run_invalid_sql_trace_expected_on")
    if not expect_sql_trace and observed_any:
        raise PerfBaselineError("run_invalid_sql_trace_expected_off")


def _validate_run_metrics(endpoint_code: str, run_rows: list[dict[str, Any]]) -> None:
    for row in run_rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, dict):
            raise PerfBaselineError(f"run_invalid_missing_metrics:{endpoint_code}")
        non_2xx = int(metrics.get("non_2xx") or 0)
        if non_2xx > 0:
            raise PerfBaselineError(f"run_invalid_non_2xx:{endpoint_code}:non_2xx={non_2xx}")


def _assert_2xx(status: int, body: dict[str, Any] | None, action: str) -> dict[str, Any]:
    if 200 <= int(status) < 300:
        return body if isinstance(body, dict) else {}
    detail = None
    if isinstance(body, dict):
        detail = body.get("detail")
    raise PerfBaselineError(f"{action}_failed:{status}:{detail}")


def _create_local_token(claims: dict[str, Any]) -> str:
    try:
        from app.core.auth import create_access_token

        return str(create_access_token(dict(claims)))
    except Exception as exc:  # noqa: BLE001
        raise PerfBaselineError(f"local_token_creation_failed:{exc}") from exc


def _bootstrap_demo(*, api_base: str, timeout_seconds: float, orders_to_seed: int, step_up_code: str | None) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"tenant-perf-{suffix}"
    owner_sub = f"owner+{suffix}@{tenant_id}.local"

    super_token = _create_local_token(
        {
            "sub": f"superadmin+{suffix}@ops.local",
            "roles": ["SUPERADMIN"],
            "tenant_id": "platform",
            "perms": ["TENANTS.WRITE", "LICENSES.WRITE", "IAM.WRITE", "ORDERS.WRITE", "ORDERS.READ", "IAM.READ", "LICENSES.READ"],
        }
    )
    super_auth = _auth_header(super_token) or ""

    step_headers = {"X-Step-Up-Code": str(step_up_code)} if str(step_up_code or "").strip() else None

    status, body, _ = _json_request(
        method="POST",
        url=f"{str(api_base).rstrip('/')}/admin/tenants/bootstrap-demo",
        auth=super_auth,
        timeout_seconds=timeout_seconds,
        payload={"tenant_id": tenant_id, "name": f"Perf Baseline {tenant_id}"},
        extra_headers=step_headers,
    )
    _assert_2xx(status, body, "bootstrap_tenant")

    status, body, _ = _json_request(
        method="POST",
        url=f"{str(api_base).rstrip('/')}/licenses/admin/issue-core",
        auth=super_auth,
        timeout_seconds=timeout_seconds,
        payload={"tenant_id": tenant_id, "plan_code": "CORE8", "valid_days": 30},
        extra_headers=step_headers,
    )
    _assert_2xx(status, body, "issue_core")

    status, body, _ = _json_request(
        method="POST",
        url=f"{str(api_base).rstrip('/')}/licenses/admin/issue-module-trial",
        auth=super_auth,
        timeout_seconds=timeout_seconds,
        payload={"tenant_id": tenant_id, "module_code": "MODULE_ORDERS"},
        extra_headers=step_headers,
    )
    _assert_2xx(status, body, "issue_orders_module_trial")

    status, body, _ = _json_request(
        method="POST",
        url=f"{str(api_base).rstrip('/')}/admin/tenants/{tenant_id}/bootstrap-first-admin",
        auth=super_auth,
        timeout_seconds=timeout_seconds,
        payload={"user_id": owner_sub, "email": owner_sub, "allow_if_exists": True, "issue_credentials": False},
        extra_headers=step_headers,
    )
    _assert_2xx(status, body, "bootstrap_first_admin")

    tenant_token = _create_local_token(
        {
            "sub": owner_sub,
            "roles": ["TENANT_ADMIN"],
            "tenant_id": tenant_id,
            "perms": ["ORDERS.READ", "ORDERS.WRITE", "IAM.READ", "LICENSES.READ"],
        }
    )
    tenant_auth = _auth_header(tenant_token) or ""

    first_order_id = ""
    for idx in range(max(1, int(orders_to_seed))):
        status, body, _ = _json_request(
            method="POST",
            url=f"{str(api_base).rstrip('/')}/orders",
            auth=tenant_auth,
            timeout_seconds=timeout_seconds,
            payload={
                "order_no": f"PERF-{suffix}-{idx:04d}",
                "status": "DRAFT",
                "transport_mode": "ROAD",
                "direction": "OUTBOUND",
                "customer_name": "Perf Baseline",
                "pickup_location": "Sofia",
                "delivery_location": "Plovdiv",
                "cargo_description": "General cargo",
                "reference_no": f"REF-{idx:04d}",
                "payload": {"seed": True, "idx": idx},
            },
        )
        created = _assert_2xx(status, body, "seed_order")
        if not first_order_id:
            order_obj = created.get("order") if isinstance(created, dict) else None
            first_order_id = str((order_obj or {}).get("id") or "").strip()

    if not first_order_id:
        raise PerfBaselineError("seed_order_missing_id")

    return {
        "tenant_id": tenant_id,
        "tenant_token": tenant_token,
        "first_order_id": first_order_id,
        "owner_sub": owner_sub,
    }


def _discover_order_id(*, api_base: str, list_path: str, auth: str, timeout_seconds: float) -> str | None:
    status, body, _ = _json_request(
        method="GET",
        url=f"{str(api_base).rstrip('/')}{list_path}",
        auth=auth,
        timeout_seconds=timeout_seconds,
    )
    if status < 200 or status >= 300 or not isinstance(body, dict):
        return None
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0] if isinstance(items[0], dict) else {}
    order_id = str(first.get("id") or "").strip()
    return order_id or None


def _run_endpoint_benchmark(
    *,
    endpoint_code: str,
    path: str,
    api_base: str,
    auth: str,
    timeout_seconds: float,
    workers: int,
    requests_per_run: int,
    runs: int,
    warmup_requests: int,
) -> dict[str, Any]:
    run_rows: list[dict[str, Any]] = []

    for run_idx in range(1, max(1, int(runs)) + 1):
        _reset_perf_snapshot(api_base=api_base, timeout_seconds=timeout_seconds)

        for _ in range(max(0, int(warmup_requests))):
            _request_once(api_base=api_base, path=path, auth=auth, timeout_seconds=timeout_seconds)

        load_metrics = _run_load(
            api_base=api_base,
            path=path,
            auth=auth,
            workers=workers,
            total_requests=requests_per_run,
            timeout_seconds=timeout_seconds,
        )
        perf_snapshot = _get_perf_snapshot(api_base=api_base, timeout_seconds=timeout_seconds)

        run_rows.append(
            {
                "run": run_idx,
                "metrics": load_metrics,
                "perf_snapshot": perf_snapshot,
            }
        )

    _validate_run_metrics(endpoint_code=endpoint_code, run_rows=run_rows)

    throughput = [float((row.get("metrics") or {}).get("throughput_rps") or 0.0) for row in run_rows]
    p50 = [float((row.get("metrics") or {}).get("p50_ms") or 0.0) for row in run_rows]
    p95 = [float((row.get("metrics") or {}).get("p95_ms") or 0.0) for row in run_rows]

    return {
        "endpoint_code": endpoint_code,
        "path": path,
        "runs": run_rows,
        "summary": {
            "runs": len(run_rows),
            "throughput_rps_median": round(statistics.median(throughput), 2) if throughput else 0.0,
            "p50_ms_median": round(statistics.median(p50), 2) if p50 else 0.0,
            "p95_ms_median": round(statistics.median(p95), 2) if p95 else 0.0,
        },
    }


def _default_out(mode: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d-orders-db-baseline")
    safe_mode = str(mode or "custom").strip().lower().replace(" ", "_")
    entitlement_mode = _resolve_entitlement_query_mode()
    return _BASE_DIR / "docs" / "perf" / d / f"orders_db_backed_baseline_{safe_mode}_{entitlement_mode}_{ts}.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DB-backed protected Orders baseline harness")
    p.add_argument(
        "--mode",
        choices=sorted(SUPPORTED_MODES),
        default=MODE_BASELINE_NO_TRACE,
        help="Canonical run mode: baseline_no_trace or diagnostic_trace.",
    )
    p.add_argument("--api-base", default="http://127.0.0.1:8100", help="API base URL")
    p.add_argument("--tenant-token", default="", help="Tenant bearer token")
    p.add_argument("--bootstrap-demo", action="store_true", help="Bootstrap ephemeral tenant/license/orders for baseline")
    p.add_argument("--bootstrap-orders", type=int, default=30, help="Orders to seed when --bootstrap-demo is enabled")
    p.add_argument("--bootstrap-step-up-code", default="", help="Optional X-Step-Up-Code header for superadmin bootstrap endpoints")
    p.add_argument("--orders-list-path", default="/orders?status=DRAFT&limit=50", help="Protected orders list path")
    p.add_argument("--lightweight-path", default="/iam/me/access", help="Lightweight protected baseline path")
    p.add_argument("--orders-read-path-template", default="/orders/{order_id}", help="Orders detail path template")
    p.add_argument("--workers", type=int, default=None, help="Parallel workers per endpoint run")
    p.add_argument("--requests-per-run", type=int, default=None, help="Requests per endpoint run")
    p.add_argument("--runs", type=int, default=None, help="Number of runs per endpoint")
    p.add_argument("--warmup-requests", type=int, default=None, help="Warmup requests before each run")
    p.add_argument(
        "--cooldown-seconds",
        type=int,
        default=None,
        help="Cooldown guard between baseline_no_trace invocations (default: mode-specific).",
    )
    p.add_argument("--timeout-seconds", type=float, default=8.0, help="Per-request timeout")
    p.add_argument("--startup-max-wait-seconds", type=float, default=45.0, help="Max wait for /healthz + /readyz.")
    p.add_argument("--startup-poll-seconds", type=float, default=1.0, help="Polling interval while waiting for readiness.")
    p.add_argument("--startup-stable-checks", type=int, default=3, help="Consecutive healthy+ready checks required.")
    p.add_argument(
        "--require-profiling-enabled",
        action="store_true",
        help="Fail fast if /healthz/perf reports profiling.enabled=false.",
    )
    p.add_argument(
        "--forbid-profiling-enabled",
        action="store_true",
        help="Fail fast if /healthz/perf reports profiling.enabled=true.",
    )
    p.add_argument(
        "--expect-sql-trace",
        choices=["auto", "on", "off"],
        default="auto",
        help="Validate SQL trace visibility from perf snapshot.",
    )
    p.add_argument("--out", default="", help="Output JSON path")
    return p.parse_args()


def _resolve_mode_config(args: argparse.Namespace) -> dict[str, Any]:
    mode = str(args.mode or "").strip().lower()
    if mode not in SUPPORTED_MODES:
        raise PerfBaselineError(f"unsupported_mode:{mode}")

    defaults = MODE_DEFAULTS[mode]

    workers = int(args.workers) if args.workers is not None else int(defaults["workers"])
    requests_per_run = (
        int(args.requests_per_run)
        if args.requests_per_run is not None
        else int(defaults["requests_per_run"])
    )
    runs = int(args.runs) if args.runs is not None else int(defaults["runs"])
    warmup_requests = (
        int(args.warmup_requests)
        if args.warmup_requests is not None
        else int(defaults["warmup_requests"])
    )
    cooldown_seconds = int(args.cooldown_seconds) if args.cooldown_seconds is not None else int(defaults["cooldown_seconds"])

    require_profiling_enabled = bool(args.require_profiling_enabled)
    forbid_profiling_enabled = bool(args.forbid_profiling_enabled)
    if not require_profiling_enabled and not forbid_profiling_enabled:
        require_profiling_enabled = bool(defaults["require_profiling_enabled"])
        forbid_profiling_enabled = bool(defaults["forbid_profiling_enabled"])
    if require_profiling_enabled and forbid_profiling_enabled:
        raise PerfBaselineError("invalid_mode_config:profiling_on_and_off")

    expect_sql_trace = bool(defaults["expect_sql_trace"])
    expect_sql_trace_raw = str(args.expect_sql_trace or "auto").strip().lower()
    if expect_sql_trace_raw == "on":
        expect_sql_trace = True
    elif expect_sql_trace_raw == "off":
        expect_sql_trace = False

    return {
        "mode": mode,
        "workers": max(1, workers),
        "requests_per_run": max(1, requests_per_run),
        "runs": max(1, runs),
        "warmup_requests": max(0, warmup_requests),
        "cooldown_seconds": max(0, cooldown_seconds),
        "require_profiling_enabled": bool(require_profiling_enabled),
        "forbid_profiling_enabled": bool(forbid_profiling_enabled),
        "expect_sql_trace": bool(expect_sql_trace),
    }


def main() -> int:
    args = _parse_args()
    api_base = str(args.api_base).rstrip("/")
    timeout_seconds = max(0.2, float(args.timeout_seconds))
    mode_config = _resolve_mode_config(args)

    runtime_readiness = _wait_for_runtime_ready(
        api_base=api_base,
        timeout_seconds=timeout_seconds,
        max_wait_seconds=max(1.0, float(args.startup_max_wait_seconds)),
        poll_seconds=max(0.2, float(args.startup_poll_seconds)),
        stable_checks=max(1, int(args.startup_stable_checks)),
    )

    initial_profiling = _get_perf_snapshot(api_base=api_base, timeout_seconds=timeout_seconds)
    _validate_profiling_mode(
        profiling=initial_profiling,
        require_enabled=bool(mode_config["require_profiling_enabled"]),
        forbid_enabled=bool(mode_config["forbid_profiling_enabled"]),
    )

    cooldown_info = _apply_cooldown_guard(
        mode=str(mode_config["mode"]),
        cooldown_seconds=int(mode_config["cooldown_seconds"]),
    )

    tenant_token = str(args.tenant_token or "").strip()
    discovered_order_id = None
    bootstrap_info: dict[str, Any] | None = None

    if bool(args.bootstrap_demo):
        bootstrap_info = _bootstrap_demo(
            api_base=api_base,
            timeout_seconds=timeout_seconds,
            orders_to_seed=max(1, int(args.bootstrap_orders)),
            step_up_code=str(args.bootstrap_step_up_code or "").strip() or None,
        )
        tenant_token = str(bootstrap_info.get("tenant_token") or "").strip()
        discovered_order_id = str(bootstrap_info.get("first_order_id") or "").strip() or None

    auth = _auth_header(tenant_token)
    if not auth:
        raise PerfBaselineError("tenant_token_required_or_enable_bootstrap_demo")

    if discovered_order_id is None:
        discovered_order_id = _discover_order_id(
            api_base=api_base,
            list_path=str(args.orders_list_path),
            auth=auth,
            timeout_seconds=timeout_seconds,
        )

    endpoints: list[tuple[str, str]] = [
        ("orders_list", str(args.orders_list_path)),
        ("protected_lightweight", str(args.lightweight_path)),
    ]

    if discovered_order_id:
        detail_path = str(args.orders_read_path_template).replace("{order_id}", discovered_order_id)
        endpoints.insert(1, ("orders_read", detail_path))

    endpoint_results: list[dict[str, Any]] = []
    for code, path in endpoints:
        endpoint_results.append(
            _run_endpoint_benchmark(
                endpoint_code=code,
                path=path,
                api_base=api_base,
                auth=auth,
                timeout_seconds=timeout_seconds,
                workers=int(mode_config["workers"]),
                requests_per_run=int(mode_config["requests_per_run"]),
                runs=int(mode_config["runs"]),
                warmup_requests=int(mode_config["warmup_requests"]),
            )
        )

    _validate_sql_trace_across_results(
        endpoint_results=endpoint_results,
        expect_sql_trace=bool(mode_config["expect_sql_trace"]),
    )

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out(str(mode_config["mode"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_base": api_base,
        "baseline_kind": "orders_protected_db_backed",
        "mode": str(mode_config["mode"]),
        "run_validation": {
            "runtime_ready": True,
            "profiling_mode_ok": True,
            "sql_trace_mode_ok": True,
            "non_2xx_allowed": False,
            "acceptance_rule": "all_runs_non_2xx_must_be_zero",
        },
        "startup_sequence": {
            "max_wait_seconds": float(max(1.0, float(args.startup_max_wait_seconds))),
            "poll_seconds": float(max(0.2, float(args.startup_poll_seconds))),
            "stable_checks": int(max(1, int(args.startup_stable_checks))),
            "observed": runtime_readiness,
        },
        "cooldown_guard": cooldown_info,
        "bootstrap": {
            "enabled": bool(args.bootstrap_demo),
            "tenant_id": (bootstrap_info or {}).get("tenant_id") if isinstance(bootstrap_info, dict) else None,
            "owner_sub": (bootstrap_info or {}).get("owner_sub") if isinstance(bootstrap_info, dict) else None,
            "seeded_order_id": discovered_order_id,
        },
        "config": {
            "workers": int(mode_config["workers"]),
            "requests_per_run": int(mode_config["requests_per_run"]),
            "runs": int(mode_config["runs"]),
            "warmup_requests": int(mode_config["warmup_requests"]),
            "cooldown_seconds": int(mode_config["cooldown_seconds"]),
            "timeout_seconds": timeout_seconds,
            "require_profiling_enabled": bool(mode_config["require_profiling_enabled"]),
            "forbid_profiling_enabled": bool(mode_config["forbid_profiling_enabled"]),
            "expect_sql_trace": bool(mode_config["expect_sql_trace"]),
            "initial_perf_enabled": bool(initial_profiling.get("enabled")),
            "entitlement_query_mode": _resolve_entitlement_query_mode(),
            "orders_list_path": str(args.orders_list_path),
            "lightweight_path": str(args.lightweight_path),
            "orders_read_included": bool(discovered_order_id),
        },
        "endpoints": endpoint_results,
    }

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "ok": True,
        "mode": str(mode_config["mode"]),
        "out_file": str(out_path),
        "orders_read_included": bool(discovered_order_id),
        "endpoints": [
            {
                "endpoint_code": row.get("endpoint_code"),
                "path": row.get("path"),
                "throughput_rps_median": ((row.get("summary") or {}).get("throughput_rps_median")),
                "p50_ms_median": ((row.get("summary") or {}).get("p50_ms_median")),
                "p95_ms_median": ((row.get("summary") or {}).get("p95_ms_median")),
            }
            for row in endpoint_results
        ],
    }
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PerfBaselineError as exc:
        print(json.dumps({"ok": False, "detail": str(exc)}, ensure_ascii=True))
        raise SystemExit(2)
