from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import threading
import time
import urllib.error
import urllib.request

DEFAULT_STAGES = [30, 50, 80, 130, 210, 340, 550]
DEFAULT_EXCLUDE_PREFIXES = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/dev-token",
]
HARD_EXCLUDE_PATHS = {"/healthz/db"}
LIKELY_PROTECTED_PREFIXES = [
    "/admin/",
    "/guard/",
    "/licenses/",
    "/marketplace/",
    "/profile/",
    "/superadmin/",
    "/support/",
    "/iam/",
    "/orders",
]

_TLS = threading.local()


def _parse_csv_list(raw: str | None) -> list[str]:
    val = str(raw or "").strip()
    if not val:
        return []
    out: list[str] = []
    for part in val.split(","):
        item = part.strip()
        if item and item not in out:
            out.append(item)
    return out


def _parse_stages(raw: str | None) -> list[int]:
    val = str(raw or "").strip()
    if not val:
        return list(DEFAULT_STAGES)

    out: list[int] = []
    for part in val.split(","):
        item = part.strip()
        if not item:
            continue
        stage = int(item)
        if stage > 0 and stage not in out:
            out.append(stage)

    if not out:
        raise ValueError("stages_empty")
    out.sort()
    return out


def _auth_value(token: str | None) -> str | None:
    tok = str(token or "").strip()
    if not tok:
        return None
    if tok.lower().startswith("bearer "):
        return tok
    return f"Bearer {tok}"


def _get_thread_opener() -> urllib.request.OpenerDirector:
    opener = getattr(_TLS, "opener", None)
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.HTTPHandler())
        setattr(_TLS, "opener", opener)
    return opener


def _open_url(req: urllib.request.Request, *, timeout_seconds: float):
    opener = _get_thread_opener()
    return opener.open(req, timeout=timeout_seconds)  # noqa: S310


def _request_json(url: str, *, auth: str | None, timeout_seconds: float) -> dict:
    req = urllib.request.Request(url=url, method="GET")
    req.add_header("Connection", "keep-alive")
    if auth:
        req.add_header("Authorization", auth)
    with _open_url(req, timeout_seconds=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _load_openapi(api_base: str, *, auth: str | None, timeout_seconds: float) -> dict:
    base = str(api_base).rstrip("/")
    return _request_json(f"{base}/openapi.json", auth=auth, timeout_seconds=timeout_seconds)


def _build_targets(
    openapi: dict,
    *,
    include_prefixes: list[str],
    exclude_prefixes: list[str],
    token_present: bool,
    include_protected_without_token: bool,
    max_endpoints: int,
) -> list[str]:
    paths_obj = (openapi or {}).get("paths") or {}
    out: list[str] = []

    for raw_path, operations in paths_obj.items():
        path = str(raw_path or "").strip()
        if not path:
            continue
        if "{" in path or "}" in path:
            continue
        if path in HARD_EXCLUDE_PATHS:
            continue

        if include_prefixes and not any(path.startswith(x) for x in include_prefixes):
            continue
        if any(path.startswith(x) for x in exclude_prefixes):
            continue

        ops = operations or {}
        get_op = ops.get("get") if isinstance(ops, dict) else None
        if get_op is None:
            continue

        if not token_present and not include_protected_without_token:
            if any(path.startswith(prefix) for prefix in LIKELY_PROTECTED_PREFIXES):
                continue
            sec = get_op.get("security") if isinstance(get_op, dict) else None
            if isinstance(sec, list) and len(sec) > 0:
                continue

        if path not in out:
            out.append(path)

    out.sort()
    return out[: max(1, min(int(max_endpoints), 5000))]


def _request_once(
    *,
    api_base: str,
    path: str,
    auth: str | None,
    timeout_seconds: float,
) -> dict:
    base = str(api_base).rstrip("/")
    url = f"{base}{path}"

    req = urllib.request.Request(url=url, method="GET")
    req.add_header("Connection", "keep-alive")
    if auth:
        req.add_header("Authorization", auth)

    started = time.perf_counter()
    try:
        with _open_url(req, timeout_seconds=timeout_seconds) as resp:
            _ = resp.read(64)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status = int(resp.getcode())
            return {
                "ok": 200 <= status < 300,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "error": None,
                "timeout": False,
                "infra_error": False,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status = int(getattr(exc, "code", 0) or 0)
        return {
            "ok": False,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "error": f"http_error:{status}",
            "timeout": False,
            "infra_error": bool(status >= 500),
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
            "timeout": bool(timeout_like),
            "infra_error": True,
        }
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": "timeout",
            "timeout": True,
            "infra_error": True,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"exception:{exc}",
            "timeout": False,
            "infra_error": True,
        }
def _compute_percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    q = statistics.quantiles(values, n=100)
    idx = max(0, min(99, int(percentile) - 1))
    return float(q[idx])


def _health_check(
    *,
    api_base: str,
    auth: str | None,
    timeout_seconds: float,
    health_paths: list[str],
) -> dict:
    base = str(api_base).rstrip("/")
    items: list[dict] = []

    for p in health_paths:
        path = str(p or "").strip()
        if not path:
            continue
        url = f"{base}{path if path.startswith('/') else '/' + path}"

        req = urllib.request.Request(url=url, method="GET")
        req.add_header("Connection", "keep-alive")
        if auth:
            req.add_header("Authorization", auth)

        started = time.perf_counter()
        try:
            with _open_url(req, timeout_seconds=timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                ok_status = 200 <= int(resp.getcode()) < 300
                parsed = None
                try:
                    parsed = json.loads(body)
                except Exception:  # noqa: BLE001
                    parsed = None
                items.append(
                    {
                        "path": path,
                        "ok": bool(ok_status),
                        "status": int(resp.getcode()),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "body": parsed,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            items.append(
                {
                    "path": path,
                    "ok": False,
                    "status": 0,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "error": str(exc),
                }
            )

    healthy = all(bool(x.get("ok")) for x in items) if items else False
    return {"ok": healthy, "checks": items}


def _filter_accessible_targets(
    *,
    api_base: str,
    auth: str | None,
    target_paths: list[str],
    timeout_seconds: float,
    only_2xx: bool,
) -> tuple[list[str], dict]:
    accessible: list[str] = []
    filtered: list[str] = []
    status_counts: dict[str, int] = {}

    for path in target_paths:
        row = _request_once(
            api_base=api_base,
            path=path,
            auth=auth,
            timeout_seconds=timeout_seconds,
        )
        status = int(row.get("status") or 0)
        status_counts[str(status)] = int(status_counts.get(str(status), 0)) + 1

        if only_2xx:
            if 200 <= status < 300:
                accessible.append(path)
            else:
                filtered.append(path)
        else:
            if status in (401, 403):
                filtered.append(path)
            else:
                accessible.append(path)

    return accessible, {
        "filtered_count": len(filtered),
        "accessible_count": len(accessible),
        "filtered_sample": filtered[:20],
        "preflight_status_counts": status_counts,
        "mode": ("only_2xx" if only_2xx else "exclude_401_403"),
    }

def _run_stage(
    *,
    api_base: str,
    auth: str | None,
    target_paths: list[str],
    stage_concurrency: int,
    requests_per_session: int,
    timeout_seconds: float,
    workers_cap: int,
) -> dict:
    workers = max(1, min(int(stage_concurrency), int(workers_cap)))
    total_requests = max(1, int(stage_concurrency)) * max(1, int(requests_per_session))

    paths = [target_paths[i % len(target_paths)] for i in range(total_requests)]

    started = time.perf_counter()
    rows: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(
                _request_once,
                api_base=api_base,
                path=p,
                auth=auth,
                timeout_seconds=timeout_seconds,
            )
            for p in paths
        ]
        for fut in as_completed(futs):
            rows.append(fut.result())

    duration_s = max(0.001, time.perf_counter() - started)

    latencies = [float(x.get("elapsed_ms") or 0.0) for x in rows]
    ok_count = sum(1 for x in rows if bool(x.get("ok")))
    timeout_count = sum(1 for x in rows if bool(x.get("timeout")))
    non_2xx_count = len(rows) - ok_count
    non_2xx_rate = float(non_2xx_count) / float(max(1, len(rows)))
    infra_error_count = sum(1 for x in rows if bool(x.get("infra_error")))
    infra_error_rate = float(infra_error_count) / float(max(1, len(rows)))

    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    for x in rows:
        status = str(int(x.get("status") or 0))
        status_counts[status] = int(status_counts.get(status, 0)) + 1
        err = str(x.get("error") or "").strip()
        if err:
            error_counts[err] = int(error_counts.get(err, 0)) + 1

    top_errors = [
        {"error": k, "count": v}
        for k, v in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]

    return {
        "stage_concurrency": int(stage_concurrency),
        "workers_used": workers,
        "requests_per_session": int(requests_per_session),
        "total_requests": len(rows),
        "ok_2xx": ok_count,
        "errors": infra_error_count,
        "error_rate": round(infra_error_rate, 6),
        "non_2xx": non_2xx_count,
        "non_2xx_rate": round(non_2xx_rate, 6),
        "timeouts": timeout_count,
        "duration_seconds": round(duration_s, 3),
        "throughput_rps": round(float(len(rows)) / duration_s, 2),
        "avg_ms": round(float(sum(latencies) / max(1, len(latencies))), 2),
        "p95_ms": round(_compute_percentile(latencies, 95), 2),
        "p99_ms": round(_compute_percentile(latencies, 99), 2),
        "max_ms": round(float(max(latencies) if latencies else 0.0), 2),
        "status_counts": status_counts,
        "top_errors": top_errors,
    }
def _default_out_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"load_staged_{ts}.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Staged load test runner with Fibonacci-friendly defaults")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--token", default="", help="Bearer token (optional)")
    p.add_argument("--stages", default=",".join(str(x) for x in DEFAULT_STAGES), help="CSV concurrency stages")
    p.add_argument("--requests-per-session", type=int, default=1, help="Requests generated by each concurrent session")
    p.add_argument("--workers-cap", type=int, default=256, help="Upper cap for worker threads")
    p.add_argument("--timeout-seconds", type=float, default=6.0, help="Per-request timeout")
    p.add_argument("--max-endpoints", type=int, default=80, help="Max GET endpoints selected from OpenAPI")
    p.add_argument("--include-prefixes", default="", help="CSV list of prefixes to include")
    p.add_argument("--exclude-prefixes", default=",".join(DEFAULT_EXCLUDE_PREFIXES), help="CSV list of prefixes to exclude")
    p.add_argument("--include-protected-without-token", action="store_true", help="Probe protected GET endpoints even without token")
    p.add_argument("--health-paths", default="/healthz,/healthz/db", help="CSV health endpoints checked before each stage")
    p.add_argument("--max-error-rate", type=float, default=0.05, help="Fail threshold for stage error rate")
    p.add_argument("--max-p95-ms", type=float, default=1200.0, help="Fail threshold for stage p95 latency")
    p.add_argument("--stop-on-fail", action="store_true", help="Stop at first stage that fails thresholds")
    p.add_argument("--include-non-2xx-targets", action="store_true", help="Do not prefilter targets by 2xx preflight")
    p.add_argument("--out", default="", help="Output JSON path")
    return p.parse_args()

def main() -> int:
    args = _parse_args()

    auth = _auth_value(args.token)
    timeout_seconds = max(0.2, float(args.timeout_seconds))

    stages = _parse_stages(args.stages)
    include_prefixes = _parse_csv_list(args.include_prefixes)
    exclude_prefixes = _parse_csv_list(args.exclude_prefixes)
    health_paths = _parse_csv_list(args.health_paths)

    openapi = _load_openapi(str(args.api_base), auth=auth, timeout_seconds=timeout_seconds)
    targets = _build_targets(
        openapi,
        include_prefixes=include_prefixes,
        exclude_prefixes=exclude_prefixes,
        token_present=bool(auth),
        include_protected_without_token=bool(args.include_protected_without_token),
        max_endpoints=int(args.max_endpoints),
    )

    if not targets:
        print(json.dumps({"ok": False, "detail": "no_target_paths"}, ensure_ascii=False))
        return 2

    target_filter = {
        "filtered_count": 0,
        "accessible_count": len(targets),
        "filtered_sample": [],
        "preflight_status_counts": {},
        "mode": "none",
    }
    if not bool(args.include_non_2xx_targets):
        targets, target_filter = _filter_accessible_targets(
            api_base=str(args.api_base),
            auth=auth,
            target_paths=targets,
            timeout_seconds=timeout_seconds,
            only_2xx=True,
        )
        if not targets:
            print(json.dumps({"ok": False, "detail": "no_accessible_targets_after_preflight", "target_filter": target_filter}, ensure_ascii=False))
            return 2

    stage_results: list[dict] = []
    overall_pass = True

    for stage in stages:
        health = _health_check(
            api_base=str(args.api_base),
            auth=auth,
            timeout_seconds=timeout_seconds,
            health_paths=health_paths,
        )
        if not bool(health.get("ok")):
            result = {
                "stage_concurrency": int(stage),
                "passed": False,
                "reason": "health_check_failed",
                "health": health,
            }
            stage_results.append(result)
            overall_pass = False
            if bool(args.stop_on_fail):
                break
            continue

        metrics = _run_stage(
            api_base=str(args.api_base),
            auth=auth,
            target_paths=targets,
            stage_concurrency=int(stage),
            requests_per_session=int(args.requests_per_session),
            timeout_seconds=timeout_seconds,
            workers_cap=int(args.workers_cap),
        )

        pass_error = float(metrics.get("error_rate") or 0.0) <= float(args.max_error_rate)
        pass_p95 = float(metrics.get("p95_ms") or 0.0) <= float(args.max_p95_ms)
        passed = bool(pass_error and pass_p95)

        metrics["passed"] = passed
        metrics["thresholds"] = {
            "max_error_rate": float(args.max_error_rate),
            "max_p95_ms": float(args.max_p95_ms),
            "pass_error_rate": pass_error,
            "pass_p95_ms": pass_p95,
        }
        metrics["health"] = health

        stage_results.append(metrics)

        if not passed:
            overall_pass = False
            if bool(args.stop_on_fail):
                break

    summary = {
        "stages_planned": stages,
        "stages_executed": [int(x.get("stage_concurrency") or 0) for x in stage_results],
        "stages_passed": sum(1 for x in stage_results if bool(x.get("passed"))),
        "stages_failed": sum(1 for x in stage_results if not bool(x.get("passed"))),
        "overall_pass": overall_pass,
    }

    report = {
        "ok": True,
        "summary": summary,
        "meta": {
            "api_base": str(args.api_base).rstrip("/"),
            "token_used": bool(auth),
            "targets_count": len(targets),
            "targets_sample": targets[:10],
            "target_filter": target_filter,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "requests_per_session": int(args.requests_per_session),
                "workers_cap": int(args.workers_cap),
                "timeout_seconds": timeout_seconds,
                "max_error_rate": float(args.max_error_rate),
                "max_p95_ms": float(args.max_p95_ms),
                "stop_on_fail": bool(args.stop_on_fail),
            },
        },
        "stages": stage_results,
    }

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "summary": summary, "out_file": str(out_path)}, ensure_ascii=False))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())