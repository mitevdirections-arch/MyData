from pathlib import Path
import importlib.util


def _load_bug_finder():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "bug_finder.py"
    spec = importlib.util.spec_from_file_location("bug_finder", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_target_paths_get_only_and_filters() -> None:
    mod = _load_bug_finder()
    openapi = {
        "paths": {
            "/healthz": {"get": {}},
            "/auth/dev-token": {"post": {}},
            "/public/profile/{tenant_id}": {"get": {}},
            "/admin/storage/policy": {"get": {"security": [{"bearerAuth": []}]}},
            "/public/country-engine/version": {"get": {}},
        }
    }

    paths = mod.build_target_paths(
        openapi,
        include_prefixes=["/public", "/healthz", "/admin"],
        exclude_prefixes=["/auth"],
        token_present=False,
        include_protected_without_token=False,
        max_endpoints=100,
    )

    assert "/healthz" in paths
    assert "/public/country-engine/version" in paths
    assert "/admin/storage/policy" not in paths
    assert "/public/profile/{tenant_id}" not in paths


def test_analyze_results_flags_unstable_and_hanging() -> None:
    mod = _load_bug_finder()
    scans = [
        {"path": "/x", "status": 200, "elapsed_ms": 120.0, "error": None},
        {"path": "/x", "status": 503, "elapsed_ms": 140.0, "error": "http_error:503"},
        {"path": "/x", "status": 0, "elapsed_ms": 6100.0, "error": "timeout", "timeout": True},
        {"path": "/y", "status": 200, "elapsed_ms": 40.0, "error": None},
    ]

    report = mod.analyze_results(scans, slow_ms_threshold=1000.0)
    by_path = {x["path"]: x for x in report["endpoints"]}

    assert by_path["/x"]["flags"]["unstable"] is True
    assert by_path["/x"]["flags"]["hanging"] is True
    assert by_path["/x"]["flags"]["slow"] is True
    assert by_path["/y"]["flags"]["unstable"] is False