param(
  [int]$Port = 8100,
  [int]$RoutesMax = 5000
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $scriptDir 'run-dev.ps1') -Port $Port -PrintRoutes -RoutesMax $RoutesMax
