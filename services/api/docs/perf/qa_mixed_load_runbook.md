# QA Mixed-Load Canonical Policy (Stability + Speed)

## Scope
Tooling-only policy for `scripts/qa_mixed_load.py`.
No app/business/authz logic changes.

## Goal
Prevent false-positive "good" runs and keep only production-like stable mixed-load evidence.

## Canonical Command
```powershell
Set-Location 'C:\Users\mitev\OneDrive\Документи\MyData\services\api'
$env:PYTHONPATH='.'
py .\scripts\qa_mixed_load.py `
  --api-base http://127.0.0.1:8150 `
  --tenant-token $env:TENANT_TOKEN `
  --super-token $env:SUPER_TOKEN `
  --runs 3 `
  --iterations 20 `
  --workers 20 `
  --timeout-seconds 8
```

## Default Fail-Closed Gates
By default, `qa_mixed_load.py` now fails unless all are true:
1. Runtime readiness is healthy (`/healthz` and `/readyz` with `ready=true`).
2. `error_rate <= 0.0`.
3. `non_2xx_rate <= 0.0`.
4. HTTP `429` max per run `<= 0`.
5. `p95_ms` is within configured threshold (`--max-p95-ms`, default `1200`).

### Protected Token Integrity Guard
If protected tokens are provided:
- prefilter `401` for `tenant` or `superadmin` group fails the run by default
- detail: `prefilter_invalid_token_for_protected_group`

This prevents public-only fallback from being interpreted as a mixed-load success.

## Optional Relaxation (debug only)
To allow protected prefilter `401` for investigation (not for headline verdict):
```powershell
--allow-protected-auth-prefilter-401
```

## Acceptance Rule (headline)
Accept run only if:
- `summary.overall_pass == true`
- `summary.non_2xx_rate == 0`
- `summary.status_429_max == 0`
- `meta.targets_count.tenant > 0`
- `meta.targets_count.superadmin > 0`

## Notes
- Summary metrics are median-based across `--runs` (default `3`).
- Strict gates use worst observed run for fail-closed behavior.
