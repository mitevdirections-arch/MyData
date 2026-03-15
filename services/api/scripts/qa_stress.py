from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path


PROFILE_DEFAULTS: dict[str, dict[str, float | int]] = {
    "quick": {
        "iterations": 2,
        "workers": 8,
        "timeout_seconds": 5.0,
        "slow_ms_threshold": 1500.0,
        "max_endpoints": 200,
    },
    "nightly": {
        "iterations": 8,
        "workers": 20,
        "timeout_seconds": 8.0,
        "slow_ms_threshold": 1200.0,
        "max_endpoints": 500,
    },
    "stress": {
        "iterations": 20,
        "workers": 40,
        "timeout_seconds": 10.0,
        "slow_ms_threshold": 1000.0,
        "max_endpoints": 800,
    },
}


def _load_bug_finder_module():
    path = Path(__file__).resolve().with_name("bug_finder.py")
    spec = importlib.util.spec_from_file_location("bug_finder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("bug_finder_loader_not_available")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def get_profile_settings(profile: str) -> dict[str, float | int]:
    key = str(profile or "nightly").strip().lower()
    if key not in PROFILE_DEFAULTS:
        raise ValueError("profile_invalid")
    return dict(PROFILE_DEFAULTS[key])


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="QA stress runner (quick/nightly/stress) over bug_finder")
    p.add_argument("--api-base", required=True, help="API base URL")
    p.add_argument("--token", default="", help="Bearer token (optional)")
    p.add_argument("--profile", choices=sorted(PROFILE_DEFAULTS.keys()), default="nightly", help="QA profile")
    p.add_argument("--include-prefixes", default="", help="CSV include path prefixes")
    p.add_argument("--exclude-prefixes", default="/docs,/redoc,/openapi.json,/auth/dev-token", help="CSV exclude path prefixes")
    p.add_argument("--include-protected-without-token", action="store_true", help="Probe protected GET endpoints without token")
    p.add_argument("--out", default="", help="Optional output file")
    return p.parse_args()


def _default_out_path(profile: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("artifacts") / f"qa_stress_{profile}_{ts}.json"


def main() -> int:
    args = _parse_args()
    bug_finder = _load_bug_finder_module()

    cfg = get_profile_settings(str(args.profile))
    token = str(args.token or "").strip() or None

    openapi = bug_finder.load_openapi(str(args.api_base), token=token, timeout_seconds=float(cfg["timeout_seconds"]))
    targets = bug_finder.build_target_paths(
        openapi,
        include_prefixes=_parse_csv_list(args.include_prefixes),
        exclude_prefixes=_parse_csv_list(args.exclude_prefixes),
        token_present=bool(token),
        include_protected_without_token=bool(args.include_protected_without_token),
        max_endpoints=int(cfg["max_endpoints"]),
    )

    if not targets:
        print(json.dumps({"ok": False, "detail": "no_target_paths"}, ensure_ascii=False))
        return 2

    scans = bug_finder.run_scan(
        api_base=str(args.api_base),
        target_paths=targets,
        token=token,
        iterations=int(cfg["iterations"]),
        workers=int(cfg["workers"]),
        timeout_seconds=float(cfg["timeout_seconds"]),
    )
    report = bug_finder.analyze_results(scans, slow_ms_threshold=float(cfg["slow_ms_threshold"]))

    report["meta"] = {
        "api_base": str(args.api_base).rstrip("/"),
        "profile": str(args.profile),
        "token_used": bool(token),
        "config": cfg,
        "target_paths": targets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(str(args.out).strip()) if str(args.out).strip() else _default_out_path(str(args.profile))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "summary": report.get("summary", {}), "out_file": str(out_path)}, ensure_ascii=False))

    suspects = int((report.get("summary") or {}).get("suspect_endpoints") or 0)
    return 1 if suspects > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())