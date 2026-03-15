# Launcher Canary Smoke (Local, Inactive)

This flow does not change the active runtime entrypoint (`app.main:app`).

## Start Foundation canary

```powershell
$api=(Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData\services\api" -Directory | Select-Object -First 1).FullName
cd $api
powershell -ExecutionPolicy Bypass -File .\scripts\run-foundation-canary.ps1 -Port 8110
```

## Start Operational canary

```powershell
$api=(Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData\services\api" -Directory | Select-Object -First 1).FullName
cd $api
powershell -ExecutionPolicy Bypass -File .\scripts\run-operational-canary.ps1 -Port 8120
```

## Smoke check boot + OpenAPI + no plane leakage

Run in a third terminal while both canary processes are up:

```powershell
$api=(Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData\services\api" -Directory | Select-Object -First 1).FullName
cd $api
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-canary-openapi.ps1
```

Expected `ok=true` with:
- foundation has `/marketplace/catalog` and does not have `/orders`
- operational has `/orders` and does not have `/marketplace/catalog`
