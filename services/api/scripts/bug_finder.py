from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
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


def _json_request(url: str, *, token: str | None, timeout_seconds: float) -> dict:
    req = urllib.request.Request(url=url, method="GET")
    if token:
        req.add_header("Authorization", token if token.lower().startswith("bearer ") else f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def load_openapi(api_base: str, *, token: str | None, timeout_seconds: float) -> dict:
    base = str(api_base).rstrip("/")
    return _json_request(f"{base}/openapi.json", token=token, timeout_seconds=timeout_seconds)


def build_target_paths(
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

        if include_prefixes and not any(path.startswith(x) for x in include_prefixes):
            continue
        if any(path.startswith(x) for x in exclude_prefixes):
            continue

        ops = operations or {}
        get_op = ops.get("get") if isinstance(ops, dict) else None
        if get_op is None:
            continue

        if not token_present and not include_protected_without_token:
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
    token: str | None,
    timeout_seconds: float,
) -> dict:
    base = str(api_base).rstrip("/")
    url = f"{base}{path}"

    req = urllib.request.Request(url=url, method="GET")
    if token:
        req.add_header("Authorization", token if token.lower().startswith("bearer ") else f"Bearer {token}")

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            _ = resp.read(128)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "ok": True,
                "path": path,
                "status": int(resp.getcode()),
                "elapsed_ms": elapsed_ms,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "path": path,
            "status": int(getattr(exc, "code", 0) or 0),
            "elapsed_ms": elapsed_ms,
            "error": f"http_error:{exc}",
        }
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        reason = str(getattr(exc, "reason", "url_error"))
        timeout_like = "timed out" in reason.lower() or "timeout" in reason.lower()
        return {
            "ok": False,
            "path": path,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"network_error:{reason}",
            "timeout": bool(timeout_like),
        }
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "path": path,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": "timeout",
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "path": path,
            "status": 0,
            "elapsed_ms": elapsed_ms,
            "error": f"exception:{exc}",
        }


def run_scan(
    *,
    api_base: str,
    target_paths: list[str],
    token: str | None,
    iterations: int,
    workers: int,
    timeout_seconds: float,
) -> list[dict]:
    scans: list[dict] = []
    iters = max(1, min(int(iterations), 200))
    max_workers = max(1, min(int(workers), 128))

    for _ in range(iters):
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [
                pool.submit(
                    _request_once,
                    api_base=api_base,
                    path=path,
                    token=token,
                    timeout_seconds=timeout_seconds,
                )
                for path in target_paths
            ]
            for fut in as_completed(futs):
                scans.append(fut.result())
    return scans


def analyze_results(
    scans: list[dict],
    *,
    slow_ms_threshold: float,
) -> dict:
    by_path: dict[str, list[dict]] = {}
    for row in scans:
        p = str(row.get("path") or "")
        if not p:
            continue
        by_path.setdefault(p, []).append(row)

    endpoints: list[dict] = []
    suspects: list[dict] = []

    for path, rows in sorted(by_path.items(), key=lambda x: x[0]):
        latencies = [float(x.get("elapsed_ms") or 0.0) for x in rows]
        statuses = [int(x.get("status") or 0) for x in rows]

        status_counts: dict[str, int] = {}
        for st in statuses:
            status_counts[str(st)] = int(status_counts.get(str(st), 0)) + 1

        timeout_count = sum(1 for x in rows if bool(x.get("timeout")))
        error_count = sum(1 for x in rows if int(x.get("status") or 0) >= 500 or str(x.get("error") or ""))
        ok_count = sum(1 for x in rows if 200 <= int(x.get("status") or 0) < 300)

        p95 = 0.0
        if latencies:
            if len(latencies) == 1:
                p95 = latencies[0]
            else:
                p95 = statistics.quantiles(latencies, n=100)[94]

        unstable = ok_count > 0 and (timeout_count > 0 or any(int(k) >= 500 for k in status_counts.keys()))
        slow = p95 >= float(slow_ms_threshold)
        hanging = timeout_count > 0

        item = {
            "path": path,
            "samples": len(rows),
            "ok_2xx": ok_count,
            "errors": error_count,
            "timeouts": timeout_count,
            "avg_ms": round(float(sum(latencies) / max(1, len(latencies))), 2),
            "p95_ms": round(float(p95), 2),
            "max_ms": round(float(max(latencies) if latencies else 0.0), 2),
            "status_counts": status_counts,
            "flags": {
                "unstable": unstable,
                "slow": slow,
                "hanging": hanging,
            },
        }
        endpoints.append(item)

        if unstable or slow or hanging:
            suspects.append(item)

    summary = {
        "scanned_paths": len(by_path),
        "total_samples": len(scans),
        "suspect_endpoints": len(suspects),
        "slow_threshold_ms": float(slow_ms_threshold),
    }
    return {
        "summary": summary,
        "suspects": suspects,
        "endpoints": endpoints,
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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bug finder: endpoint instability / timeout / slow-response scanner")
    p.add_argument("--api-base", required=True, help="API base URL (e.g. http://127.0.0.1:8100)")
    p.add_argument("--token", default="", help="Bearer token (optional)")
    p.add_argument("--iterations", type=int, default=4, help="How many full scan rounds")
    p.add_argument("--workers", type=int, default=12, help="Parallel request workers")
    p.add_argument("--timeout-seconds", type=float, default=6.0, help="Per-request timeout")
    p.add_argument("--slow-ms-threshold", type=float, default=1500.0, help="P95 threshold for slow endpoint flag")
    p.add_argument("--max-endpoints", type=int, default=400, help="Max GET endpoints to probe")
    p.add_argument("--include-prefixes", default="", help="CSV list of path prefixes to include")
    p.add_argument("--exclude-prefixes", default=",".join(DEFAULT_EXCLUDE_PREFIXES), help="CSV list of path prefixes to exclude")
    p.add_argument("--include-protected-without-token", action="store_true", help="Probe protected GET endpoints even when token is missing")
    p.add_argument("--out", default="", help="Optional output file path (JSON)")
    return p.parse_args()


def _default_out_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"bug_finder_report_{ts}.json"


def main() -> int:
    args = _parse_args()

    token = str(args.token or "").strip() or None
    include_prefixes = _parse_csv_list(args.include_prefixes)
    exclude_prefixes = _parse_csv_list(args.exclude_prefixes)

    openapi = load_openapi(str(args.api_base), token=token, timeout_seconds=max(1.0, float(args.timeout_seconds)))
    targets = build_target_paths(
        openapi,
        include_prefixes=include_prefixes,
        exclude_prefixes=exclude_prefixes,
        token_present=bool(token),
        include_protected_without_token=bool(args.include_protected_without_token),
        max_endpoints=int(args.max_endpoints),
    )

    if not targets:
        out = {
            "ok": False,
            "detail": "no_target_paths",
            "hint": "Check include/exclude filters or openapi availability",
        }
        print(json.dumps(out, ensure_ascii=False))
        return 2

    scans = run_scan(
        api_base=str(args.api_base),
        target_paths=targets,
        token=token,
        iterations=int(args.iterations),
        workers=int(args.workers),
        timeout_seconds=max(0.5, float(args.timeout_seconds)),
    )

    report = analyze_results(scans, slow_ms_threshold=float(args.slow_ms_threshold))
    report["meta"] = {
        "api_base": str(args.api_base).rstrip("/"),
        "iterations": int(args.iterations),
        "workers": int(args.workers),
        "timeout_seconds": float(args.timeout_seconds),
        "token_used": bool(token),
        "target_paths": targets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "summary": report.get("summary", {}),
                "out_file": str(out_path),
            },
            ensure_ascii=False,
        )
    )

    suspects = int((report.get("summary") or {}).get("suspect_endpoints") or 0)
    return 1 if suspects > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())