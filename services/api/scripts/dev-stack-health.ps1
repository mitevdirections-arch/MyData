param(
  [string]$ApiHost = "127.0.0.1",
  [int]$ApiPort = 8150,
  [int]$DbPort = 26257
)

$ErrorActionPreference = "Stop"

function Test-PortOpen {
  param(
    [string]$TargetHost = "127.0.0.1",
    [int]$Port,
    [int]$TimeoutMs = 700
  )

  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $ar = $client.BeginConnect($TargetHost, $Port, $null, $null)
    $ok = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
    if (-not $ok) { return $false }
    $client.EndConnect($ar) | Out-Null
    return $true
  } catch {
    return $false
  } finally {
    $client.Dispose()
  }
}

$dbOk = Test-PortOpen -TargetHost "127.0.0.1" -Port $DbPort
Write-Host ("db_port_{0}: {1}" -f $DbPort, $dbOk)

try {
  $url = "http://{0}:{1}/healthz" -f $ApiHost, $ApiPort
  $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
  Write-Host ("api_healthz: {0}" -f (($resp | ConvertTo-Json -Compress)))
} catch {
  Write-Host "api_healthz: unavailable"
}
