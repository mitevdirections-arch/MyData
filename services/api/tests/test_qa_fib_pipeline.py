from pathlib import Path
import importlib.util


def _load_pipeline():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "qa_fib_pipeline.py"
    spec = importlib.util.spec_from_file_location("qa_fib_pipeline", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_stages_default_and_custom() -> None:
    mod = _load_pipeline()
    assert mod._parse_stages("") == [30, 50, 80, 130, 210, 340, 550]
    assert mod._parse_stages("130,50,50,30") == [30, 50, 130]


def test_evaluate_gates_pass() -> None:
    mod = _load_pipeline()
    metrics = {
        "error_rate": 0.0,
        "non_2xx_rate": 0.01,
        "p95_ms": 320.0,
        "throughput_rps": 220.0,
    }
    gates = mod._evaluate_gates(
        metrics=metrics,
        max_error_rate=0.05,
        max_non_2xx_rate=0.05,
        max_p95_ms=1200.0,
        min_throughput_rps=100.0,
    )
    assert gates["passed"] is True
    assert gates["checks"]["pass_error_rate"] is True
    assert gates["checks"]["pass_non_2xx_rate"] is True
    assert gates["checks"]["pass_p95_ms"] is True
    assert gates["checks"]["pass_min_throughput"] is True


def test_evaluate_gates_fail_on_limits() -> None:
    mod = _load_pipeline()
    metrics = {
        "error_rate": 0.07,
        "non_2xx_rate": 0.12,
        "p95_ms": 1800.0,
        "throughput_rps": 40.0,
    }
    gates = mod._evaluate_gates(
        metrics=metrics,
        max_error_rate=0.05,
        max_non_2xx_rate=0.05,
        max_p95_ms=1200.0,
        min_throughput_rps=80.0,
    )
    assert gates["passed"] is False
    assert gates["checks"]["pass_error_rate"] is False
    assert gates["checks"]["pass_non_2xx_rate"] is False
    assert gates["checks"]["pass_p95_ms"] is False
    assert gates["checks"]["pass_min_throughput"] is False


def test_evaluate_gates_no_min_rps() -> None:
    mod = _load_pipeline()
    metrics = {
        "error_rate": 0.0,
        "non_2xx_rate": 0.0,
        "p95_ms": 200.0,
        "throughput_rps": 10.0,
    }
    gates = mod._evaluate_gates(
        metrics=metrics,
        max_error_rate=0.05,
        max_non_2xx_rate=0.05,
        max_p95_ms=1200.0,
        min_throughput_rps=0.0,
    )
    assert gates["passed"] is True
    assert gates["checks"]["pass_min_throughput"] is True