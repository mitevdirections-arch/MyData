from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import random

DEFAULT_FIB_STAGES = [30, 50, 80, 130, 210, 340, 550]
DEFAULT_HEALTH_PATHS = ["/healthz", "/healthz/db"]
DEFAULT_EXCLUDE_PREFIXES = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/dev-token",
]


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
        return list(DEFAULT_FIB_STAGES)

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


def _load_script_module(file_name: str, module_name: str):
    path = Path(__file__).resolve().with_name(file_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_loader_unavailable:{file_name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _evaluate_gates(
    *,
    metrics: dict,
    max_error_rate: float,
    max_non_2xx_rate: float,
    max_p95_ms: float,
    min_throughput_rps: float,
) -> dict:
    error_rate = float(metrics.get("error_rate") or 0.0)
    non_2xx_rate = float(metrics.get("non_2xx_rate") or 0.0)
    p95_ms = float(metrics.get("p95_ms") or 0.0)
    throughput_rps = float(metrics.get("throughput_rps") or 0.0)

    pass_error_rate = error_rate <= float(max_error_rate)
    pass_non_2xx_rate = non_2xx_rate <= float(max_non_2xx_rate)
    pass_p95_ms = p95_ms <= float(max_p95_ms)

    min_rps = max(0.0, float(min_throughput_rps))
    pass_min_throughput = throughput_rps >= min_rps if min_rps > 0.0 else True

    passed = bool(pass_error_rate and pass_non_2xx_rate and pass_p95_ms and pass_min_throughput)

    return {
        "passed": passed,
        "thresholds": {
            "max_error_rate": float(max_error_rate),
            "max_non_2xx_rate": float(max_non_2xx_rate),
            "max_p95_ms": float(max_p95_ms),
            "min_throughput_rps": float(min_rps),
        },
        "checks": {
            "pass_error_rate": pass_error_rate,
            "pass_non_2xx_rate": pass_non_2xx_rate,
            "pass_p95_ms": pass_p95_ms,
            "pass_min_throughput": pass_min_throughput,
        },
        "observed": {
            "error_rate": round(error_rate, 6),
            "non_2xx_rate": round(non_2xx_rate, 6),
            "p95_ms": round(p95_ms, 2),
            "throughput_rps": round(throughput_rps, 2),
        },
    }


def _default_out_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"qa_fib_pipeline_{ts}.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fibonacci staged mixed-load pipeline with hard fail gates")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--tenant-token", default="", help="Tenant bearer token")
    p.add_argument("--super-token", default="", help="Superadmin bearer token")
    p.add_argument("--stages", default=",".join(str(x) for x in DEFAULT_FIB_STAGES), help="CSV Fibonacci-like stages")
    p.add_argument("--iterations-per-stage", type=int, default=2, help="Requests per worker in each stage")
    p.add_argument("--workers-cap", type=int, default=256, help="Worker upper cap per stage")
    p.add_argument("--timeout-seconds", type=float, default=6.0, help="Per-request timeout")
    p.add_argument("--max-endpoints-per-group", type=int, default=40, help="Target cap per group")
    p.add_argument("--public-weight", type=int, default=30, help="Traffic weight for public routes")
    p.add_argument("--tenant-weight", type=int, default=50, help="Traffic weight for tenant routes")
    p.add_argument("--superadmin-weight", type=int, default=20, help="Traffic weight for superadmin routes")
    p.add_argument("--include-prefixes", default="", help="CSV include path prefixes")
    p.add_argument("--exclude-prefixes", default=",".join(DEFAULT_EXCLUDE_PREFIXES), help="CSV exclude path prefixes")
    p.add_argument("--health-paths", default=",".join(DEFAULT_HEALTH_PATHS), help="CSV health endpoints before each stage")
    p.add_argument("--include-non-2xx-targets", action="store_true", help="Skip strict 2xx prefilter")
    p.add_argument("--max-error-rate", type=float, default=0.05, help="Hard gate: max infra error rate")
    p.add_argument("--max-non-2xx-rate", type=float, default=0.05, help="Hard gate: max non-2xx rate")
    p.add_argument("--max-p95-ms", type=float, default=1200.0, help="Hard gate: max stage p95 latency")
    p.add_argument("--min-throughput-rps", type=float, default=0.0, help="Hard gate: minimum stage throughput")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument("--continue-on-fail", action="store_true", help="Continue after failed gate (default is stop)")
    p.add_argument("--out", default="", help="Output JSON path")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    mixed = _load_script_module("qa_mixed_load.py", "qa_mixed_load")
    staged = _load_script_module("qa_staged_load.py", "qa_staged_load")

    random.seed(int(args.seed))

    api_base = str(args.api_base).rstrip("/")
    timeout_seconds = max(0.2, float(args.timeout_seconds))
    stages = _parse_stages(args.stages)

    auth_by_group = {
        "public": None,
        "tenant": mixed._auth_value(args.tenant_token),
        "superadmin": mixed._auth_value(args.super_token),
    }
    weights = {
        "public": max(0, int(args.public_weight)),
        "tenant": max(0, int(args.tenant_weight)),
        "superadmin": max(0, int(args.superadmin_weight)),
    }

    include_prefixes = _parse_csv_list(args.include_prefixes)
    exclude_prefixes = _parse_csv_list(args.exclude_prefixes)
    health_paths = _parse_csv_list(args.health_paths)

    openapi = mixed._load_openapi(api_base=api_base, timeout_seconds=timeout_seconds)
    targets = mixed._build_targets(
        openapi,
        include_prefixes=include_prefixes,
        exclude_prefixes=exclude_prefixes,
        max_per_group=int(args.max_endpoints_per_group),
    )

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
        targets, prefilter = mixed._prefilter_targets(
            api_base=api_base,
            targets_by_group=targets,
            auth_by_group=auth_by_group,
            timeout_seconds=timeout_seconds,
            only_2xx=True,
        )

    if not any(targets.values()):
        print(json.dumps({"ok": False, "detail": "no_targets_after_prefilter", "prefilter": prefilter}, ensure_ascii=False))
        return 2

    stage_results: list[dict] = []
    overall_pass = True

    for stage in stages:
        health = staged._health_check(
            api_base=api_base,
            auth=None,
            timeout_seconds=timeout_seconds,
            health_paths=health_paths,
        )
        if not bool(health.get("ok")):
            row = {
                "stage_concurrency": int(stage),
                "workers_used": max(1, min(int(stage), int(args.workers_cap))),
                "iterations_per_stage": max(1, int(args.iterations_per_stage)),
                "passed": False,
                "reason": "health_check_failed",
                "health": health,
            }
            stage_results.append(row)
            overall_pass = False
            if not bool(args.continue_on_fail):
                break
            continue

        stage_seed = int(args.seed) + int(stage)
        random.seed(stage_seed)

        workers = max(1, min(int(stage), int(args.workers_cap)))
        metrics = mixed._run_mixed(
            api_base=api_base,
            targets_by_group=targets,
            auth_by_group=auth_by_group,
            weights=weights,
            workers=workers,
            iterations=max(1, int(args.iterations_per_stage)),
            timeout_seconds=timeout_seconds,
        )

        gates = _evaluate_gates(
            metrics=metrics,
            max_error_rate=float(args.max_error_rate),
            max_non_2xx_rate=float(args.max_non_2xx_rate),
            max_p95_ms=float(args.max_p95_ms),
            min_throughput_rps=float(args.min_throughput_rps),
        )

        row = {
            "stage_concurrency": int(stage),
            "workers_used": workers,
            "iterations_per_stage": max(1, int(args.iterations_per_stage)),
            "passed": bool(gates.get("passed")),
            "gates": gates,
            "metrics": metrics,
            "health": health,
            "seed_used": stage_seed,
        }
        stage_results.append(row)

        if not bool(gates.get("passed")):
            overall_pass = False
            if not bool(args.continue_on_fail):
                break

    executed = [int(x.get("stage_concurrency") or 0) for x in stage_results]
    passed_stages = [int(x.get("stage_concurrency") or 0) for x in stage_results if bool(x.get("passed"))]
    failed_stages = [int(x.get("stage_concurrency") or 0) for x in stage_results if not bool(x.get("passed"))]

    summary = {
        "overall_pass": bool(overall_pass),
        "stages_planned": stages,
        "stages_executed": executed,
        "stages_passed": passed_stages,
        "stages_failed": failed_stages,
        "max_passed_stage": (max(passed_stages) if passed_stages else None),
        "first_failed_stage": (failed_stages[0] if failed_stages else None),
    }

    report = {
        "ok": True,
        "summary": summary,
        "meta": {
            "api_base": api_base,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "token_used": {
                "tenant": bool(auth_by_group["tenant"]),
                "superadmin": bool(auth_by_group["superadmin"]),
            },
            "weights": weights,
            "prefilter": prefilter,
            "targets_count": {k: len(v) for k, v in targets.items()},
            "targets_sample": {k: v[:10] for k, v in targets.items()},
            "config": {
                "stages": stages,
                "iterations_per_stage": max(1, int(args.iterations_per_stage)),
                "workers_cap": int(args.workers_cap),
                "timeout_seconds": timeout_seconds,
                "max_endpoints_per_group": int(args.max_endpoints_per_group),
                "health_paths": health_paths,
                "max_error_rate": float(args.max_error_rate),
                "max_non_2xx_rate": float(args.max_non_2xx_rate),
                "max_p95_ms": float(args.max_p95_ms),
                "min_throughput_rps": float(args.min_throughput_rps),
                "continue_on_fail": bool(args.continue_on_fail),
                "seed": int(args.seed),
            },
        },
        "stages": stage_results,
    }

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "summary": summary, "out_file": str(out_path)}, ensure_ascii=False))
    return 0 if bool(overall_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())