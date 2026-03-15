param(
  [int]$Port = 8110,
  [switch]$PrintRoutes,
  [int]$RoutesMax = 2000
)

$env:PYTHONPATH = "./"

if ($PrintRoutes) {
  $env:API_STARTUP_ROUTES_PRINT_ENABLED = "true"
  $env:API_STARTUP_ROUTES_PRINT_MAX = "$RoutesMax"
  Write-Host "[foundation-canary] startup route dump enabled (max=$RoutesMax)"
} else {
  if (-not $env:API_STARTUP_ROUTES_PRINT_ENABLED) { $env:API_STARTUP_ROUTES_PRINT_ENABLED = "false" }
  if (-not $env:API_STARTUP_ROUTES_PRINT_MAX) { $env:API_STARTUP_ROUTES_PRINT_MAX = "2000" }
}

Write-Host "[foundation-canary] starting on http://127.0.0.1:$Port"
py -m uvicorn app.main_foundation_canary:app --reload --host 127.0.0.1 --port $Port --log-level debug
