from pathlib import Path
import importlib.util


def _load_qa_stress():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "qa_stress.py"
    spec = importlib.util.spec_from_file_location("qa_stress", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_get_profile_settings_quick() -> None:
    mod = _load_qa_stress()
    cfg = mod.get_profile_settings("quick")
    assert int(cfg["iterations"]) == 2
    assert int(cfg["workers"]) == 8


def test_get_profile_settings_invalid_raises() -> None:
    mod = _load_qa_stress()
    try:
        mod.get_profile_settings("unknown")
        assert False, "expected ValueError"
    except ValueError:
        assert True