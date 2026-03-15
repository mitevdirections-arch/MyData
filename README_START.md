# MyData Quick Start

This file is a minimal local start guide for MyData API.

## 1) Start CockroachDB (MyData local helper)
```powershell
$MYDATA = (Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData" -Directory | Select-Object -First 1).FullName
cd $MYDATA
powershell -ExecutionPolicy Bypass -File .\bin\crdb-start-only.ps1
Test-NetConnection 127.0.0.1 -Port 26257
```
Expected: `TcpTestSucceeded : True`

## 2) Prepare API environment
```powershell
cd "$MYDATA\services\api"
Copy-Item .env.example .env -ErrorAction SilentlyContinue
```

Fill required values in `.env`:
- `DATABASE_URL`
- `JWT_SECRET`
- `STORAGE_ACCESS_KEY`
- `STORAGE_SECRET_KEY`
- `STORAGE_GRANT_SECRET`
- `GUARD_BOT_SIGNING_MASTER_SECRET`

Important:
- Keep `.env` local only.
- Never commit real credentials to repository files.

## 3) Install and migrate
```powershell
cd "$MYDATA\services\api"
$env:PYTHONPATH='.'
py -m pip install -e .
py -m alembic upgrade head
```

## 4) Start API
Official local startup contract for the API is the MyData helper script inside this repo.

```powershell
cd "$MYDATA\services\api"
powershell -ExecutionPolicy Bypass -File .\scripts\api-quick.ps1 -Port 8100
```

This starts the API from the MyData repository only and prints the loaded routes on startup.

## 5) Health checks
```powershell
curl.exe --max-time 8 http://127.0.0.1:8100/healthz
curl.exe --max-time 8 http://127.0.0.1:8100/readyz
curl.exe --max-time 8 http://127.0.0.1:8100/healthz/db
```
Contract:
- `/healthz` = process liveness only.
- `/readyz` = strict readiness (DB config + DB connectivity are mandatory).
- `/healthz/db` = detailed DB probe payload.

## Zero-retention policy
- Customer files are not stored permanently.
- DB stores metadata only.
- Verification docs are temporary by policy.


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

