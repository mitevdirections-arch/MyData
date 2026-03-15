# MyData Runbook (DEV)

## Scope
Use dynamic paths so this works when OneDrive folder names are localized.

```powershell
$MYDATA = (Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData" -Directory | Select-Object -First 1).FullName
$API = Join-Path $MYDATA "services\api"
$INFRA = Join-Path $MYDATA "infrastructure"
```

## 1) Start CockroachDB (MyData local helper)
```powershell
cd $MYDATA
powershell -ExecutionPolicy Bypass -File .\bin\crdb-start-only.ps1
Test-NetConnection 127.0.0.1 -Port 26257
```

## 2) Start MinIO
```powershell
cd $INFRA
docker compose up -d minio
```

Set credentials via environment before startup (example):
```powershell
$env:MINIO_ROOT_USER="set-me"
$env:MINIO_ROOT_PASSWORD="set-me-strong"
```

## 3) API setup
```powershell
cd $API
Copy-Item .env.example .env -ErrorAction SilentlyContinue
$env:PYTHONPATH="."
py -m pip install -e .
```

Required `.env` keys:
- `DATABASE_URL`
- `JWT_SECRET`
- `STORAGE_ACCESS_KEY`
- `STORAGE_SECRET_KEY`
- `STORAGE_GRANT_SECRET`
- `GUARD_BOT_SIGNING_MASTER_SECRET`

## 4) Run DB migrations
```powershell
cd $API
$env:PYTHONPATH="."
py -m alembic upgrade head
```

## 5) Run API
Official local startup contract for the API is the MyData helper script inside this repo.

```powershell
cd $API
powershell -ExecutionPolicy Bypass -File .\scripts\api-quick.ps1 -Port 8100
```

This starts the API from the MyData repository only and prints the loaded routes on startup.

## 6) Health checks
```powershell
curl.exe --max-time 8 http://127.0.0.1:8100/healthz
curl.exe --max-time 8 http://127.0.0.1:8100/readyz
curl.exe --max-time 8 http://127.0.0.1:8100/healthz/db
```
Contract:
- `/healthz` -> liveness only.
- `/readyz` -> strict readiness; returns 503 when DB is missing/invalid/down.
- `/healthz/db` -> DB probe details for diagnostics.

## 7) Optional DEV token helper
Enable only for local QA:
- `AUTH_DEV_TOKEN_ENABLED=true`

```powershell
$tok = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8100/auth/dev-token" -ContentType "application/json" -Body '{"sub":"superadmin@ops.local","roles":["SUPERADMIN"],"tenant_id":"platform"}'
$headers = @{ Authorization = "Bearer $($tok.access_token)" }
```

## 8) Common issues
- `healthz/db` timeout:
  - Cockroach is down or `DATABASE_URL` is invalid.
- Storage/presign errors:
  - MinIO is down, bucket missing, or credentials mismatch.
- `core_license_required`:
  - Tenant has no active CORE license for protected route.

## Security notes
- Do not store real credentials in docs.
- Do not commit `.env`.
- Rotate all secrets for non-local environments.

## CI required gate
- Canonical required status check name: `operational-readiness-required`
- Coverage contract:
  - real DB migration verification (`alembic heads/current/upgrade/current`)
  - `qa_migrations_smoke.py --strict`
  - tenant isolation e2e + role separation e2e profiles
  - runtime readiness probes (`/healthz`, `/readyz`, `/healthz/db`)
  - `prod_gate.py`


## Unicode-path note (Windows)
If your MyData path contains non-ASCII characters (for example localized OneDrive folders), some DB subprocess tools may fail to resolve cert file paths.
Use an ASCII drive alias before running migrations/prod gate:

```powershell
$MYDATA = (Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData" -Directory | Select-Object -First 1).FullName
cmd /c "subst M: /D" 2>$null
cmd /c "subst M: $MYDATA"
$cert = "M:/certs/cockroach"
$env:DATABASE_URL = "cockroachdb+psycopg://root@127.0.0.1:26257/defaultdb?sslmode=verify-full&sslrootcert=$cert/ca.crt&sslcert=$cert/client.root.crt&sslkey=$cert/client.root.key"
```

