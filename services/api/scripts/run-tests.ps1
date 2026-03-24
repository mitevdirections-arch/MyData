param(
  [switch]$Verbose,
  [string]$Filter = "",
  [int]$Durations = 20
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiRoot = (Resolve-Path (Join-Path $scriptDir ".." )).Path
Set-Location $apiRoot
$env:PYTHONPATH = "."

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

$args = @("-m", "pytest")
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
exit $LASTEXITCODE
