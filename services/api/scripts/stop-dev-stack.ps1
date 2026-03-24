param(
  [int]$ApiPort = 8150,
  [switch]$StopDb
)

$ErrorActionPreference = "Stop"

$apiConns = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
if ($apiConns) {
  $pids = $apiConns.OwningProcess | Select-Object -Unique
  Get-Process -Id $pids -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match 'python|uvicorn' } |
    Stop-Process -Force
  Write-Host ("api_stopped_on_port_{0}" -f $ApiPort)
} else {
  Write-Host ("api_not_listening_on_port_{0}" -f $ApiPort)
}

if ($StopDb) {
  $cr = Get-CimInstance Win32_Process -Filter "name='cockroach.exe'" -ErrorAction SilentlyContinue
  if ($cr) {
    $cr | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Write-Host "cockroach_stopped"
  } else {
    Write-Host "cockroach_not_running"
  }
} else {
  Write-Host "cockroach_left_running"
}
