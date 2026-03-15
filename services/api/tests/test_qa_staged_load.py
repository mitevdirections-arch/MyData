from pathlib import Path
import importlib.util


def _load_staged_load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "qa_staged_load.py"
    spec = importlib.util.spec_from_file_location("qa_staged_load", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_stages_default_and_custom() -> None:
    mod = _load_staged_load()
    assert mod._parse_stages("") == [30, 50, 80, 130, 210, 340, 550]
    assert mod._parse_stages("130,50,50,30") == [30, 50, 130]


def test_build_targets_skips_path_params_and_protected_without_token() -> None:
    mod = _load_staged_load()
    openapi = {
        "paths": {
            "/healthz": {"get": {}},
            "/healthz/db": {"get": {}},
            "/public/profile/{tenant_id}": {"get": {}},
            "/admin/storage/policy": {"get": {"security": [{"bearerAuth": []}]}} ,
            "/admin/onboarding/applications": {"get": {}},
            "/public/country-engine/version": {"get": {}},
            "/auth/dev-token": {"post": {}},
        }
    }

    paths = mod._build_targets(
        openapi,
        include_prefixes=["/public", "/healthz", "/admin"],
        exclude_prefixes=["/auth"],
        token_present=False,
        include_protected_without_token=False,
        max_endpoints=100,
    )

    assert "/healthz" in paths
    assert "/healthz/db" not in paths
    assert "/public/country-engine/version" in paths
    assert "/admin/storage/policy" not in paths
    assert "/admin/onboarding/applications" not in paths
    assert "/public/profile/{tenant_id}" not in paths


def test_compute_percentile_handles_single_value() -> None:
    mod = _load_staged_load()
    assert mod._compute_percentile([42.0], 95) == 42.0