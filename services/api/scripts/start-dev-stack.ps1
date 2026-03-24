param(
  [string]$Root = "",
  [string]$ApiHost = "127.0.0.1",
  [int]$Port = 8150,
  [switch]$KillExistingApi
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($Root)) {
  $resolvedRoot = (Resolve-Path (Join-Path $scriptDir "..\..\.." )).Path
} else {
  $resolvedRoot = (Resolve-Path $Root).Path
}

$api = Join-Path $resolvedRoot "services\api"
$crdbScript = Join-Path $resolvedRoot "bin\crdb-start-only.ps1"

if (-not (Test-Path $api)) { throw "API path not found: $api" }
if (-not (Test-Path $crdbScript)) { throw "Cockroach script not found: $crdbScript" }

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  $pids = $existing.OwningProcess | Select-Object -Unique
  if (-not $KillExistingApi) {
    throw "Port $Port is already in use by PID(s): $($pids -join ', '). Use -KillExistingApi to replace the running API process."
  }

  Get-Process -Id $pids -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match 'python|uvicorn' } |
    Stop-Process -Force

  Start-Sleep -Milliseconds 400
}

if (-not (Test-NetConnection 127.0.0.1 -Port 26257 -WarningAction SilentlyContinue).TcpTestSucceeded) {
  powershell -ExecutionPolicy Bypass -File $crdbScript
}

$deadline = (Get-Date).AddSeconds(30)
do {
  Start-Sleep -Milliseconds 500
  $ready = (Test-NetConnection 127.0.0.1 -Port 26257 -WarningAction SilentlyContinue).TcpTestSucceeded
} until ($ready -or (Get-Date) -gt $deadline)

if (-not $ready) { throw "Cockroach not reachable on 127.0.0.1:26257" }

Set-Location $api
$env:PYTHONPATH='.'

py -m alembic current
if ($LASTEXITCODE -ne 0) { throw "Alembic current failed" }

py -m uvicorn app.main:app --host $ApiHost --port $Port --no-server-header --access-log --log-level info
