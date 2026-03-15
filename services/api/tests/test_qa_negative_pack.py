from pathlib import Path
import importlib.util


def _load_mod():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "qa_negative_pack.py"
    spec = importlib.util.spec_from_file_location("qa_negative_pack", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_negative_pack_runs_and_has_expected_scenarios() -> None:
    mod = _load_mod()
    out = mod.run_pack(strict=False)
    assert isinstance(out, dict)
    assert int(out.get("total") or 0) >= 6

    names = {str(x.get("scenario")) for x in list(out.get("results") or [])}
    assert "missing_authorization" in names
    assert "abuse_rate_limit" in names
    assert "tenant_breakout_header_mismatch" in names
    assert "step_up_required" in names
    assert "lockout_controls_present" in names
    assert "replay_controls_configured" in names