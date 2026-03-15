from pathlib import Path
import importlib.util
import random


def _load_qa_mixed_load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "qa_mixed_load.py"
    spec = importlib.util.spec_from_file_location("qa_mixed_load", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_targets_groups_and_skips_path_params() -> None:
    mod = _load_qa_mixed_load()
    openapi = {
        "paths": {
            "/healthz": {"get": {}},
            "/healthz/db": {"get": {}},
            "/public/country-engine/version": {"get": {}},
            "/admin/storage/policy": {"get": {}},
            "/superadmin/storage/delete-queue": {"get": {}},
            "/public/profile/{tenant_id}": {"get": {}},
            "/auth/dev-token": {"post": {}},
        }
    }

    out = mod._build_targets(
        openapi,
        include_prefixes=[],
        exclude_prefixes=["/auth"],
        max_per_group=100,
    )

    assert "/healthz" in out["public"]
    assert "/healthz/db" not in out["public"]
    assert "/public/country-engine/version" in out["public"]
    assert "/admin/storage/policy" in out["tenant"]
    assert "/superadmin/storage/delete-queue" in out["superadmin"]
    assert "/public/profile/{tenant_id}" not in out["public"]


def test_choose_group_respects_available_groups() -> None:
    mod = _load_qa_mixed_load()
    random.seed(7)
    g = mod._choose_group(["public"], {"public": 1, "tenant": 100, "superadmin": 100})
    assert g == "public"


def test_choose_group_falls_back_when_weights_zero() -> None:
    mod = _load_qa_mixed_load()
    random.seed(9)
    g = mod._choose_group(["tenant", "superadmin"], {"tenant": 0, "superadmin": 0})
    assert g in ("tenant", "superadmin")