param(
  [switch]$Verbose,
  [string]$Filter = "",
  [int]$Durations = 20
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiRoot = (Resolve-Path (Join-Path $scriptDir ".." )).Path
$projectRoot = (Resolve-Path (Join-Path $apiRoot "..\.." )).Path
Set-Location $apiRoot
$env:PYTHONPATH = "."
$env:PYTHONDONTWRITEBYTECODE = "1"

function Clear-TransientWorkspaceNoise {
  param([string]$RootPath)

  if ([string]::IsNullOrWhiteSpace($RootPath) -or -not (Test-Path $RootPath)) {
    return
  }

  Get-ChildItem $RootPath -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Get-ChildItem $RootPath -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

  $pytestCache = Join-Path $RootPath ".pytest_cache"
  if (Test-Path $pytestCache) {
    Remove-Item $pytestCache -Recurse -Force -ErrorAction SilentlyContinue
  }
}

# Lightweight dotenv support for local runs.
if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
  $dotenv = Join-Path $apiRoot ".env"
  if (Test-Path $dotenv) {
    Get-Content $dotenv | ForEach-Object {
      $line = $_.Trim()
      if (-not $line -or $line.StartsWith("#")) { return }
      $parts = $line.Split("=", 2)
      if ($parts.Count -ne 2) { return }
      $key = $parts[0].Trim()
      $val = $parts[1].Trim().Trim('"')
      if ($key -and -not (Test-Path "env:$key")) {
        Set-Item -Path "env:$key" -Value $val
      }
    }
  }
}

if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
  $ca = Join-Path $projectRoot "certs\cockroach\ca.crt"
  $crt = Join-Path $projectRoot "certs\cockroach\client.root.crt"
  $key = Join-Path $projectRoot "certs\cockroach\client.root.key"
  if ((Test-Path $ca) -and (Test-Path $crt) -and (Test-Path $key)) {
    $caUri = $ca -replace "\\", "/"
    $crtUri = $crt -replace "\\", "/"
    $keyUri = $key -replace "\\", "/"
    $env:DATABASE_URL = "cockroachdb+psycopg://root@127.0.0.1:26257/defaultdb?sslmode=verify-full&sslrootcert=$caUri&sslcert=$crtUri&sslkey=$keyUri"
    Write-Host "[tests] DATABASE_URL auto-configured from local Cockroach certs"
  }
}

$args = @("-B", "-m", "pytest")
if ($Verbose) {
  $args += @("-vv", "-ra", "--durations=$Durations")
} else {
  $args += @("-ra")
}
if ($Filter) {
  $args += @("-k", $Filter)
}

Write-Host "[tests] py $($args -join ' ')"
& py @args
$code = $LASTEXITCODE
Clear-TransientWorkspaceNoise -RootPath $apiRoot
exit $code
