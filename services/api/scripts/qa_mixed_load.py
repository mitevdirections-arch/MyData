from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import statistics
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_EXCLUDE_PREFIXES = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/dev-token",
]
HARD_EXCLUDE_PATHS = {"/healthz/db"}

GROUP_PREFIXES = {
    "public": [
        "/healthz",
        "/public/",
        "/i18n/locales",
    ],
    "tenant": [
        "/admin/",
        "/guard/device/",
        "/guard/heartbeat",
        "/guard/license-snapshot",
        "/guard/tenant-status",
        "/licenses/active",
        "/licenses/core-entitlement",
        "/licenses/module-entitlement/",
        "/marketplace/catalog",
        "/marketplace/offers/active",
        "/marketplace/purchase-requests",
        "/profile/",
        "/support/tenant/",
        "/i18n/effective",
        "/orders/",
    ],
    "superadmin": [
        "/superadmin/",
        "/licenses/admin/",
        "/marketplace/admin/",
        "/guard/admin/",
        "/support/superadmin/",
    ],
}


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


def _auth_value(token: str | None) -> str | None:
    tok = str(token or "").strip()
    if not tok:
        return None
    if tok.lower().startswith("bearer "):
        return tok
    return f"Bearer {tok}"


def _request_once(*, api_base: str, path: str, auth: str | None, timeout_seconds: float) -> dict:
    url = f"{str(api_base).rstrip('/')}{path}"
    req = urllib.request.Request(url=url, method="GET")
    if auth:
        req.add_header("Authorization", auth)

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            _ = resp.read(128)
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


def _request_json_once(*, api_base: str, path: str, timeout_seconds: float) -> tuple[int, dict[str, Any] | None, str | None]:
    url = f"{str(api_base).rstrip('/')}{path}"
    req = urllib.request.Request(url=url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            status = int(resp.getcode())
            raw = resp.read().decode("utf-8", errors="replace")
            body: dict[str, Any] | None = None
            if raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        body = parsed
                except json.JSONDecodeError:
                    body = None
            return status, body, None
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            raw = ""

        body = None
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    body = parsed
            except json.JSONDecodeError:
                body = None
        return status, body, f"http_error:{status}"
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "url_error"))
        return 0, None, f"network_error:{reason}"
    except TimeoutError:
        return 0, None, "timeout"
    except Exception as exc:  # noqa: BLE001
        return 0, None, f"exception:{exc}"


def _runtime_ready_check(*, api_base: str, timeout_seconds: float) -> tuple[bool, dict]:
    health_status, health_body, health_err = _request_json_once(
        api_base=api_base,
        path="/healthz",
        timeout_seconds=timeout_seconds,
    )
    ready_status, ready_body, ready_err = _request_json_once(
        api_base=api_base,
        path="/readyz",
        timeout_seconds=timeout_seconds,
    )

    health_ok = 200 <= int(health_status) < 300
    ready_ok = False
    ready_flag = None
    if isinstance(ready_body, dict):
        ready_flag = bool(ready_body.get("ready"))
        ready_ok = bool(ready_body.get("ok")) and ready_flag

    observed = {
        "health_status": int(health_status),
        "ready_status": int(ready_status),
        "health_ok": health_ok,
        "ready_ok": ready_ok,
        "ready_flag": ready_flag,
        "health_error": health_err,
        "ready_error": ready_err,
        "health_body": health_body,
        "ready_body": ready_body,
    }
    return bool(health_ok and ready_ok), observed


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    q = statistics.quantiles(values, n=100)
    idx = max(0, min(99, int(p) - 1))
    return float(q[idx])


def _load_openapi(api_base: str, timeout_seconds: float = 6.0) -> dict:
    req = urllib.request.Request(url=f"{str(api_base).rstrip('/')}/openapi.json", method="GET")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _group_for_path(path: str) -> str | None:
    for group in ("superadmin", "tenant", "public"):
        for prefix in GROUP_PREFIXES[group]:
            if path.startswith(prefix):
                return group
    return None


def _build_targets(
    openapi: dict,
    *,
    include_prefixes: list[str],
    exclude_prefixes: list[str],
    max_per_group: int,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"public": [], "tenant": [], "superadmin": []}
    paths_obj = (openapi or {}).get("paths") or {}

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

        ops = operations if isinstance(operations, dict) else {}
        if "get" not in ops:
            continue

        group = _group_for_path(path)
        if group is None:
            continue

        if path not in out[group]:
            out[group].append(path)

    for k in out:
        out[k].sort()
        out[k] = out[k][: max(1, min(int(max_per_group), 1000))]
    return out


def _prefilter_targets(
    *,
    api_base: str,
    targets_by_group: dict[str, list[str]],
    auth_by_group: dict[str, str | None],
    timeout_seconds: float,
    only_2xx: bool,
) -> tuple[dict[str, list[str]], dict]:
    kept: dict[str, list[str]] = {"public": [], "tenant": [], "superadmin": []}
    stats: dict[str, dict[str, int]] = {
        "public": {},
        "tenant": {},
        "superadmin": {},
    }
    dropped_total = 0

    for group, paths in targets_by_group.items():
        auth = auth_by_group.get(group)
        for path in paths:
            row = _request_once(api_base=api_base, path=path, auth=auth, timeout_seconds=timeout_seconds)
            status = int(row.get("status") or 0)
            status_key = str(status)
            stats[group][status_key] = int(stats[group].get(status_key, 0)) + 1

            if only_2xx:
                allowed = 200 <= status < 300
            else:
                allowed = status not in (401, 403)

            if allowed:
                kept[group].append(path)
            else:
                dropped_total += 1

    meta = {
        "dropped_total": int(dropped_total),
        "kept_counts": {k: len(v) for k, v in kept.items()},
        "status_counts": stats,
        "mode": ("only_2xx" if only_2xx else "exclude_401_403"),
    }
    return kept, meta


def _choose_group(groups: list[str], weights: dict[str, int]) -> str:
    if len(groups) == 1:
        return groups[0]
    active = [g for g in groups if int(weights.get(g, 0)) > 0]
    if not active:
        active = list(groups)
    vals = [max(1, int(weights.get(g, 1))) for g in active]
    return random.choices(active, weights=vals, k=1)[0]


def _run_mixed(
    *,
    api_base: str,
    targets_by_group: dict[str, list[str]],
    auth_by_group: dict[str, str | None],
    weights: dict[str, int],
    workers: int,
    iterations: int,
    timeout_seconds: float,
) -> dict:
    total = max(1, int(workers)) * max(1, int(iterations))

    active_groups = [g for g in ("public", "tenant", "superadmin") if targets_by_group.get(g)]
    if not active_groups:
        raise RuntimeError("no_active_groups")

    plan: list[tuple[str, str]] = []
    for _ in range(total):
        g = _choose_group(active_groups, weights)
        p = random.choice(targets_by_group[g])
        plan.append((g, p))

    rows: list[dict] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        future_meta: dict = {}
        futures = []
        for group, path in plan:
            fut = pool.submit(
                _request_once,
                api_base=api_base,
                path=path,
                auth=auth_by_group.get(group),
                timeout_seconds=timeout_seconds,
            )
            futures.append(fut)
            future_meta[fut] = (group, path)

        for fut in as_completed(futures):
            row = fut.result()
            group, path = future_meta.get(fut, ("public", "/healthz"))
            row["group"] = group
            row["path"] = path
            rows.append(row)

    duration = max(0.001, time.perf_counter() - started)
    lat = [float(x.get("elapsed_ms") or 0.0) for x in rows]

    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    group_summary: dict[str, dict[str, int]] = {
        "public": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
        "tenant": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
        "superadmin": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
    }

    ok_count = 0
    infra_error_count = 0
    timeout_count = 0

    for x in rows:
        status = str(int(x.get("status") or 0))
        status_counts[status] = int(status_counts.get(status, 0)) + 1

        err = str(x.get("error") or "").strip()
        if err:
            error_counts[err] = int(error_counts.get(err, 0)) + 1

        g = str(x.get("group") or "public")
        if g not in group_summary:
            group_summary[g] = {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0}
        group_summary[g]["total"] += 1

        if bool(x.get("ok")):
            ok_count += 1
            group_summary[g]["ok_2xx"] += 1
        if bool(x.get("infra_error")):
            infra_error_count += 1
            group_summary[g]["errors"] += 1
        if bool(x.get("timeout")):
            timeout_count += 1
            group_summary[g]["timeouts"] += 1

    return {
        "total_requests": len(rows),
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(float(len(rows)) / duration, 2),
        "ok_2xx": int(ok_count),
        "non_2xx": int(len(rows) - ok_count),
        "timeouts": int(timeout_count),
        "errors": int(infra_error_count),
        "error_rate": round(float(infra_error_count) / float(max(1, len(rows))), 6),
        "non_2xx_rate": round(float(len(rows) - ok_count) / float(max(1, len(rows))), 6),
        "avg_ms": round(float(sum(lat) / max(1, len(lat))), 2),
        "p95_ms": round(_percentile(lat, 95), 2),
        "p99_ms": round(_percentile(lat, 99), 2),
        "max_ms": round(float(max(lat) if lat else 0.0), 2),
        "status_counts": status_counts,
        "top_errors": [
            {"error": k, "count": v}
            for k, v in sorted(error_counts.items(), key=lambda it: (-it[1], it[0]))[:8]
        ],
        "group_summary": group_summary,
    }


def _default_out() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"qa_mixed_load_{ts}.json"


def _aggregate_run_metrics(run_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not run_rows:
        return {
            "run_count": 0,
            "runs": [],
            "total_requests": 0,
            "throughput_rps": 0.0,
            "p95_ms": 0.0,
            "error_rate": 1.0,
            "non_2xx_rate": 1.0,
            "status_429_max": 0,
            "status_counts": {},
            "group_summary": {
                "public": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
                "tenant": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
                "superadmin": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
            },
        }

    metrics_rows = [dict(x.get("metrics") or {}) for x in run_rows]

    throughput_vals = [float(x.get("throughput_rps") or 0.0) for x in metrics_rows]
    p95_vals = [float(x.get("p95_ms") or 0.0) for x in metrics_rows]
    p99_vals = [float(x.get("p99_ms") or 0.0) for x in metrics_rows]
    avg_vals = [float(x.get("avg_ms") or 0.0) for x in metrics_rows]
    max_vals = [float(x.get("max_ms") or 0.0) for x in metrics_rows]
    error_rate_vals = [float(x.get("error_rate") or 0.0) for x in metrics_rows]
    non_2xx_rate_vals = [float(x.get("non_2xx_rate") or 0.0) for x in metrics_rows]

    status_429_by_run: list[int] = []
    status_counts_agg: dict[str, int] = {}
    error_counts_agg: dict[str, int] = {}
    group_summary_agg: dict[str, dict[str, int]] = {
        "public": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
        "tenant": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
        "superadmin": {"total": 0, "ok_2xx": 0, "errors": 0, "timeouts": 0},
    }

    for row in metrics_rows:
        status_counts = row.get("status_counts") if isinstance(row.get("status_counts"), dict) else {}
        for key, val in status_counts.items():
            k = str(key)
            status_counts_agg[k] = int(status_counts_agg.get(k, 0)) + int(val or 0)
        status_429_by_run.append(int(status_counts.get("429", 0) if isinstance(status_counts, dict) else 0))

        top_errors = row.get("top_errors") if isinstance(row.get("top_errors"), list) else []
        for item in top_errors:
            if not isinstance(item, dict):
                continue
            err = str(item.get("error") or "").strip()
            cnt = int(item.get("count") or 0)
            if err:
                error_counts_agg[err] = int(error_counts_agg.get(err, 0)) + cnt

        group_summary = row.get("group_summary") if isinstance(row.get("group_summary"), dict) else {}
        for group in ("public", "tenant", "superadmin"):
            src = group_summary.get(group) if isinstance(group_summary, dict) else None
            if not isinstance(src, dict):
                continue
            dst = group_summary_agg[group]
            dst["total"] += int(src.get("total") or 0)
            dst["ok_2xx"] += int(src.get("ok_2xx") or 0)
            dst["errors"] += int(src.get("errors") or 0)
            dst["timeouts"] += int(src.get("timeouts") or 0)

    return {
        "run_count": len(run_rows),
        "runs": run_rows,
        "total_requests": int(sum(int(x.get("total_requests") or 0) for x in metrics_rows)),
        "total_requests_per_run_median": int(statistics.median([int(x.get("total_requests") or 0) for x in metrics_rows])),
        "throughput_rps": round(float(statistics.median(throughput_vals)), 2),
        "throughput_rps_min": round(float(min(throughput_vals)), 2),
        "throughput_rps_max": round(float(max(throughput_vals)), 2),
        "p95_ms": round(float(statistics.median(p95_vals)), 2),
        "p95_ms_max": round(float(max(p95_vals)), 2),
        "p99_ms": round(float(statistics.median(p99_vals)), 2),
        "avg_ms": round(float(statistics.median(avg_vals)), 2),
        "max_ms": round(float(max(max_vals)), 2),
        # Keep strict stability gating fail-closed: use worst observed rates.
        "error_rate": round(float(max(error_rate_vals)), 6),
        "error_rate_median": round(float(statistics.median(error_rate_vals)), 6),
        "non_2xx_rate": round(float(max(non_2xx_rate_vals)), 6),
        "non_2xx_rate_median": round(float(statistics.median(non_2xx_rate_vals)), 6),
        "ok_2xx": int(sum(int(x.get("ok_2xx") or 0) for x in metrics_rows)),
        "non_2xx": int(sum(int(x.get("non_2xx") or 0) for x in metrics_rows)),
        "timeouts": int(sum(int(x.get("timeouts") or 0) for x in metrics_rows)),
        "errors": int(sum(int(x.get("errors") or 0) for x in metrics_rows)),
        "status_429_max": int(max(status_429_by_run) if status_429_by_run else 0),
        "status_counts": status_counts_agg,
        "top_errors": [
            {"error": k, "count": v}
            for k, v in sorted(error_counts_agg.items(), key=lambda it: (-it[1], it[0]))[:8]
        ],
        "group_summary": group_summary_agg,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mixed load QA runner (public + tenant + superadmin)")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--tenant-token", default="", help="Tenant bearer token")
    p.add_argument("--super-token", default="", help="Superadmin bearer token")
    p.add_argument("--runs", type=int, default=3, help="Run count for median aggregation (canonical policy: 3)")
    p.add_argument("--iterations", type=int, default=20, help="Requests per worker")
    p.add_argument("--workers", type=int, default=50, help="Parallel workers")
    p.add_argument("--timeout-seconds", type=float, default=6.0, help="Per-request timeout")
    p.add_argument("--max-endpoints-per-group", type=int, default=40, help="Target cap per group")
    p.add_argument("--public-weight", type=int, default=30, help="Traffic weight: public")
    p.add_argument("--tenant-weight", type=int, default=50, help="Traffic weight: tenant")
    p.add_argument("--superadmin-weight", type=int, default=20, help="Traffic weight: superadmin")
    p.add_argument("--include-prefixes", default="", help="CSV include path prefixes")
    p.add_argument("--exclude-prefixes", default=",".join(DEFAULT_EXCLUDE_PREFIXES), help="CSV exclude path prefixes")
    p.add_argument("--include-non-2xx-targets", action="store_true", help="Skip strict prefilter of only 2xx paths")
    p.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    p.add_argument(
        "--allow-protected-auth-prefilter-401",
        action="store_true",
        help="Allow 401 in prefilter for protected groups even when token is provided (default fail-closed).",
    )
    p.add_argument("--max-error-rate", type=float, default=0.0, help="Fail threshold for infra error rate")
    p.add_argument("--max-non-2xx-rate", type=float, default=0.0, help="Fail threshold for non-2xx rate")
    p.add_argument("--max-429-count", type=int, default=0, help="Fail threshold for HTTP 429 count")
    p.add_argument("--max-p95-ms", type=float, default=1200.0, help="Fail threshold for p95 latency")
    p.add_argument("--out", default="", help="Output JSON path")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    random.seed(int(args.seed))

    api_base = str(args.api_base).rstrip("/")
    timeout_seconds = max(0.2, float(args.timeout_seconds))
    run_count = max(1, int(args.runs))

    runtime_ready, readiness = _runtime_ready_check(api_base=api_base, timeout_seconds=timeout_seconds)
    if not runtime_ready:
        print(
            json.dumps(
                {
                    "ok": False,
                    "detail": "runtime_not_ready",
                    "readiness": readiness,
                },
                ensure_ascii=False,
            )
        )
        return 2

    auth_by_group = {
        "public": None,
        "tenant": _auth_value(args.tenant_token),
        "superadmin": _auth_value(args.super_token),
    }
    weights = {
        "public": max(0, int(args.public_weight)),
        "tenant": max(0, int(args.tenant_weight)),
        "superadmin": max(0, int(args.superadmin_weight)),
    }

    openapi = _load_openapi(api_base=api_base, timeout_seconds=timeout_seconds)
    targets = _build_targets(
        openapi,
        include_prefixes=_parse_csv_list(args.include_prefixes),
        exclude_prefixes=_parse_csv_list(args.exclude_prefixes),
        max_per_group=int(args.max_endpoints_per_group),
    )

    # If token is missing, drop protected groups to avoid synthetic 401 noise.
    if auth_by_group["tenant"] is None:
        targets["tenant"] = []
    if auth_by_group["superadmin"] is None:
        targets["superadmin"] = []

    if not any(targets.values()):
        print(json.dumps({"ok": False, "detail": "no_targets_after_group_filter"}, ensure_ascii=False))
        return 2

    prefilter = {
        "mode": "none",
        "dropped_total": 0,
        "kept_counts": {k: len(v) for k, v in targets.items()},
        "status_counts": {},
    }
    if not bool(args.include_non_2xx_targets):
        targets, prefilter = _prefilter_targets(
            api_base=api_base,
            targets_by_group=targets,
            auth_by_group=auth_by_group,
            timeout_seconds=timeout_seconds,
            only_2xx=True,
        )

    if not bool(args.allow_protected_auth_prefilter_401):
        bad_groups: list[dict[str, int | str]] = []
        for group in ("tenant", "superadmin"):
            if auth_by_group.get(group) is None:
                continue
            stats = prefilter.get("status_counts", {}).get(group, {}) if isinstance(prefilter, dict) else {}
            bad_401 = int(stats.get("401", 0) if isinstance(stats, dict) else 0)
            if bad_401 > 0:
                bad_groups.append({"group": group, "http_401": bad_401})
        if bad_groups:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "detail": "prefilter_invalid_token_for_protected_group",
                        "invalid_groups": bad_groups,
                        "prefilter": prefilter,
                    },
                    ensure_ascii=False,
                )
            )
            return 2

    if not any(targets.values()):
        print(json.dumps({"ok": False, "detail": "no_targets_after_prefilter", "prefilter": prefilter}, ensure_ascii=False))
        return 2

    run_rows: list[dict[str, Any]] = []
    for idx in range(run_count):
        run_metrics = _run_mixed(
            api_base=api_base,
            targets_by_group=targets,
            auth_by_group=auth_by_group,
            weights=weights,
            workers=max(1, int(args.workers)),
            iterations=max(1, int(args.iterations)),
            timeout_seconds=timeout_seconds,
        )
        run_rows.append({"run": idx + 1, "metrics": run_metrics})
    metrics = _aggregate_run_metrics(run_rows)

    pass_error = float(metrics.get("error_rate") or 0.0) <= float(args.max_error_rate)
    pass_non_2xx = float(metrics.get("non_2xx_rate") or 0.0) <= float(args.max_non_2xx_rate)
    pass_429 = int(metrics.get("status_429_max") or 0) <= int(args.max_429_count)
    pass_p95 = float(metrics.get("p95_ms") or 0.0) <= float(args.max_p95_ms)
    overall_pass = bool(pass_error and pass_non_2xx and pass_429 and pass_p95)

    metrics["passed"] = overall_pass
    metrics["thresholds"] = {
        "max_error_rate": float(args.max_error_rate),
        "max_non_2xx_rate": float(args.max_non_2xx_rate),
        "max_429_count": int(args.max_429_count),
        "max_p95_ms": float(args.max_p95_ms),
        "pass_error_rate": pass_error,
        "pass_non_2xx_rate": pass_non_2xx,
        "pass_429_count": pass_429,
        "pass_p95_ms": pass_p95,
    }

    report = {
        "ok": True,
        "summary": {
            "overall_pass": overall_pass,
            "total_requests": metrics.get("total_requests"),
            "throughput_rps": metrics.get("throughput_rps"),
            "p95_ms": metrics.get("p95_ms"),
            "error_rate": metrics.get("error_rate"),
            "non_2xx_rate": metrics.get("non_2xx_rate"),
            "status_429_max": metrics.get("status_429_max"),
            "run_count": metrics.get("run_count"),
        },
        "meta": {
            "api_base": api_base,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "readiness": readiness,
            "token_used": {
                "tenant": bool(auth_by_group["tenant"]),
                "superadmin": bool(auth_by_group["superadmin"]),
            },
            "weights": weights,
            "config": {
                "runs": run_count,
                "workers": int(args.workers),
                "iterations": int(args.iterations),
                "timeout_seconds": timeout_seconds,
                "max_endpoints_per_group": int(args.max_endpoints_per_group),
                "max_error_rate": float(args.max_error_rate),
                "max_non_2xx_rate": float(args.max_non_2xx_rate),
                "max_429_count": int(args.max_429_count),
                "max_p95_ms": float(args.max_p95_ms),
                "allow_protected_auth_prefilter_401": bool(args.allow_protected_auth_prefilter_401),
            },
            "targets_count": {k: len(v) for k, v in targets.items()},
            "targets_sample": {k: v[:10] for k, v in targets.items()},
            "prefilter": prefilter,
        },
        "result": metrics,
    }

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "summary": report["summary"], "out_file": str(out_path)}, ensure_ascii=False))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
