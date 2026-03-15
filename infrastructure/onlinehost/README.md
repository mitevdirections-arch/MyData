# Online Host (Simple Admin Flow)

This folder is intentionally built for low-friction admin operations.

## 0) Prerequisites
- Kubernetes cluster is available.
- `kubectl` is installed and already authenticated to the right cluster.
- Ingress controller exists (for `Ingress` object).
- cert-manager is installed when `CERT_MANAGER_ENABLED=true`.

## 1) Prepare config (one file)
```powershell
$MYDATA = (Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData" -Directory | Select-Object -First 1).FullName
cd (Join-Path $MYDATA "infrastructure\onlinehost")
Copy-Item .\admin.env.example .\admin.env
```
Open `admin.env` and fill required values.

## 2) Deploy (one command)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Deploy-OnlineHost.ps1
```

## 3) Check status (one command)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Get-OnlineHostStatus.ps1
```

## Rollback (if needed)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Rollback-OnlineHost.ps1
```

## TLS modes
- Default (recommended):
  - `CERT_MANAGER_ENABLED=true`
  - Deploy script auto-creates Issuer/Certificate and binds Ingress TLS secret.
- Existing TLS secret mode:
  - `CERT_MANAGER_ENABLED=false`
  - You must pre-create `TLS_SECRET_NAME` in namespace.

## What auto-scales
- Pods auto-scale via `HPA` (`minReplicas`/`maxReplicas` from `admin.env`).
- Each pod runs fixed Uvicorn workers.
- Scale strategy: horizontal pod scaling is primary production pattern.

## Admin notes
- If deployment fails, check: `kubectl -n mydata-prod describe pod <pod-name>`
- Logs: `kubectl -n mydata-prod logs deploy/mydata-api --tail=200`
- Update image: edit `IMAGE` in `admin.env` and rerun Deploy script.