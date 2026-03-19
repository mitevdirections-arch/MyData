# Orders DB-backed Baseline Runbook (Phase 12 Stabilized)

## Goal
Repeatable protected Orders perf baseline with two canonical modes:
- `baseline_no_trace` (clean A/B baseline, minimum profiling overhead)
- `diagnostic_trace` (profiling + SQL trace for layer diagnostics)

Measured metrics:
- throughput / RPS
- p50 / p95
- status mix
- perf segments from `/healthz/perf` (diagnostic mode)

## Runtime Prerequisites
- API is running (default: `http://127.0.0.1:8100`)
- DB-ready runtime (`/readyz` must return `ready=true`)
- `DATABASE_URL` is set in API process environment
- Run from `services/api`:
  - `$env:PYTHONPATH='.'`

## Canonical Startup Sequence (fixed)
`orders_db_backed_baseline.py` now enforces before benchmark:
1. `/healthz` + `/readyz` polling
2. consecutive stable readiness checks (`--startup-stable-checks`, default `3`)
3. profiling mode validation according to selected mode
4. baseline cooldown guard for `/iam/me/access` sensitive rate-limit window
5. benchmark run only after runtime is considered stable

Default startup gate params:
- `--startup-max-wait-seconds 45`
- `--startup-poll-seconds 1`
- `--startup-stable-checks 3`

## Mode A: Clean Baseline (no trace)
Use for fair A/B throughput/latency comparison.

Required API env profile:
- `PERF_PROFILING_ENABLED=false`
- `MYDATA_PERF_SQL_TRACE=0`
- `MYDATA_PERF_ENTITLEMENT_QUERY_MODE=legacy` (default; use `core` only for experimental/proof runs)

Command:
```powershell
$env:PYTHONPATH='.'
py .\tools\perf\orders_db_backed_baseline.py `
  --mode baseline_no_trace `
  --api-base http://127.0.0.1:8100 `
  --cooldown-seconds 65 `
  --bootstrap-demo `
  --bootstrap-orders 30
```

Cooldown behavior:
- `baseline_no_trace` defaults to `--cooldown-seconds 65`.
- Harness tracks last baseline invocation in:
  `services/api/docs/perf/.orders_db_backed_baseline_state.json`
- If a new baseline starts too soon, harness waits the remaining seconds automatically.
- This prevents `/iam/me/access` rate-limit contamination (`/iam/` is a sensitive path in runtime middleware).

## Mode B: Diagnostic Trace
Use for hotspot localization only (not for clean A/B headline numbers).

Required API env profile:
- `PERF_PROFILING_ENABLED=true`
- `PERF_PROFILING_METHODS=GET`
- `PERF_PROFILING_PATH_PREFIXES=/orders,/iam/me/access`
- `MYDATA_PERF_SQL_TRACE=1`
- `MYDATA_PERF_ACCESS_BREAKDOWN=1`
- `MYDATA_PERF_PROTECTED_ENVELOPE_BREAKDOWN=1`
- `MYDATA_PERF_ENTITLEMENT_QUERY_MODE=legacy` (default; use `core` only for experimental/proof runs)

Command:
```powershell
$env:PYTHONPATH='.'
py .\tools\perf\orders_db_backed_baseline.py `
  --mode diagnostic_trace `
  --api-base http://127.0.0.1:8100 `
  --bootstrap-demo `
  --bootstrap-orders 30
```

Notes:
- `diagnostic_trace` keeps cooldown default at `0` (no forced wait).
- Do not compare diagnostic runs as clean headline performance numbers.

## Acceptance Criteria (run is valid)
A run is valid only if all are true:
1. startup/readiness gate passed;
2. profiling mode matches selected mode;
3. SQL trace visibility matches selected mode;
4. all endpoint runs have `non_2xx == 0`.

If any rule fails, harness exits fail-closed with explicit `run_invalid_*` detail.

## Fair Comparison Rules (A/B discipline)
Compare only:
- same mode (`baseline_no_trace` vs `baseline_no_trace`);
- same workers/requests/runs/warmup;
- same machine state (no heavy background load);
- close timestamps.
- for A/B proof runs, change only `MYDATA_PERF_ENTITLEMENT_QUERY_MODE` (`legacy` default vs `core` experimental).
- keep baseline cooldown guard enabled (`>=65s`) to avoid `/iam/me/access` rate-limit carry-over between invocations.

Recommended minimal repeatability check:
- run `baseline_no_trace` twice;
- compare medians per endpoint (`orders_list`, `orders_read`, `protected_lightweight`);
- if variance is large, treat result as environment drift and re-run before code conclusions.

## Output Artifacts
Default artifact path:
- `services/api/docs/perf/<yyyy-mm-dd>-orders-db-baseline/orders_db_backed_baseline_<mode>_<timestamp>.json`

Includes:
- `mode`
- startup/readiness observation
- config used for the run
- per-endpoint run rows + median summary

