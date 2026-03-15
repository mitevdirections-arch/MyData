from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import statistics
import time
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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mixed load QA runner (public + tenant + superadmin)")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--tenant-token", default="", help="Tenant bearer token")
    p.add_argument("--super-token", default="", help="Superadmin bearer token")
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
    p.add_argument("--max-error-rate", type=float, default=0.05, help="Fail threshold for infra error rate")
    p.add_argument("--max-p95-ms", type=float, default=1200.0, help="Fail threshold for p95 latency")
    p.add_argument("--out", default="", help="Output JSON path")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    random.seed(int(args.seed))

    api_base = str(args.api_base).rstrip("/")
    timeout_seconds = max(0.2, float(args.timeout_seconds))

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

    if not any(targets.values()):
        print(json.dumps({"ok": False, "detail": "no_targets_after_prefilter", "prefilter": prefilter}, ensure_ascii=False))
        return 2

    metrics = _run_mixed(
        api_base=api_base,
        targets_by_group=targets,
        auth_by_group=auth_by_group,
        weights=weights,
        workers=max(1, int(args.workers)),
        iterations=max(1, int(args.iterations)),
        timeout_seconds=timeout_seconds,
    )

    pass_error = float(metrics.get("error_rate") or 0.0) <= float(args.max_error_rate)
    pass_p95 = float(metrics.get("p95_ms") or 0.0) <= float(args.max_p95_ms)
    overall_pass = bool(pass_error and pass_p95)

    metrics["passed"] = overall_pass
    metrics["thresholds"] = {
        "max_error_rate": float(args.max_error_rate),
        "max_p95_ms": float(args.max_p95_ms),
        "pass_error_rate": pass_error,
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
        },
        "meta": {
            "api_base": api_base,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "token_used": {
                "tenant": bool(auth_by_group["tenant"]),
                "superadmin": bool(auth_by_group["superadmin"]),
            },
            "weights": weights,
            "config": {
                "workers": int(args.workers),
                "iterations": int(args.iterations),
                "timeout_seconds": timeout_seconds,
                "max_endpoints_per_group": int(args.max_endpoints_per_group),
                "max_error_rate": float(args.max_error_rate),
                "max_p95_ms": float(args.max_p95_ms),
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
