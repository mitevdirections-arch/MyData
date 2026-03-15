param(
  [string]$Root = ""
)

$ErrorActionPreference = "Stop"

if (-not $Root) {
  $Root = (Get-ChildItem "$env:USERPROFILE\OneDrive\*\MyData" -Directory | Select-Object -First 1).FullName
}
if (-not (Test-Path $Root)) {
  throw "MyData root not found: $Root"
}

$api = Join-Path $Root "services\api"
if (-not (Test-Path $api)) {
  throw "API path not found: $api"
}

$trashDirs = Get-ChildItem -Path $api -Recurse -Directory -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in @('__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.tox') }

$removedDirCount = 0
foreach ($d in $trashDirs) {
  try {
    Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Stop
    $removedDirCount++
  } catch {
    Write-Warning "Could not remove directory: $($d.FullName)"
  }
}

$artifactsPath = Join-Path $api "artifacts"
$removedArtifactCount = 0
$keptArtifacts = @()

if (Test-Path $artifactsPath) {
  $files = Get-ChildItem -Path $artifactsPath -File -ErrorAction SilentlyContinue
  $grouped = @{}

  foreach ($f in $files) {
    $name = $f.Name
    if ($name -match '^(?<base>[a-z_]+(?:_report)?)_\d{8}_\d{6}\.json$') {
      $base = $Matches['base']
    } else {
      $base = '__misc__'
    }

    if (-not $grouped.ContainsKey($base)) {
      $grouped[$base] = @()
    }
    $grouped[$base] += $f
  }

  foreach ($base in $grouped.Keys) {
    $set = $grouped[$base] | Sort-Object LastWriteTimeUtc -Descending
    $keep = $set | Select-Object -First 1
    if ($keep) {
      $keptArtifacts += $keep.FullName
    }

    $drop = $set | Select-Object -Skip 1
    foreach ($x in $drop) {
      try {
        Remove-Item -LiteralPath $x.FullName -Force -ErrorAction Stop
        $removedArtifactCount++
      } catch {
        Write-Warning "Could not remove artifact: $($x.FullName)"
      }
    }
  }
}

[pscustomobject]@{
  root = $Root
  removed_runtime_dirs = $removedDirCount
  removed_artifact_files = $removedArtifactCount
  kept_artifacts = ($keptArtifacts | Sort-Object)
} | ConvertTo-Json -Depth 4