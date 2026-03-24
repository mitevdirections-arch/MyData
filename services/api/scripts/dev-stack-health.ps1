param(
  [string]$ApiHost = "127.0.0.1",
  [int]$ApiPort = 8150,
  [int]$DbPort = 26257
)

$ErrorActionPreference = "Stop"

$dbOk = (Test-NetConnection 127.0.0.1 -Port $DbPort -WarningAction SilentlyContinue).TcpTestSucceeded
Write-Host ("db_port_{0}: {1}" -f $DbPort, $dbOk)

try {
  $url = "http://{0}:{1}/healthz" -f $ApiHost, $ApiPort
  $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
  Write-Host ("api_healthz: {0}" -f (($resp | ConvertTo-Json -Compress)))
} catch {
  Write-Host "api_healthz: unavailable"
}
