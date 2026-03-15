param(
  [switch]$Verbose,
  [string]$Filter = "",
  [int]$Durations = 20
)

$env:PYTHONPATH = "./"

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
