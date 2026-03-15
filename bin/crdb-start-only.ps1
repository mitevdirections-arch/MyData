param(
    [string]$SqlAddr = "127.0.0.1:26257",
    [string]$ListenAddr = "127.0.0.1:26258",
    [string]$HttpAddr = "127.0.0.1:8080",
    [switch]$Insecure,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

$MyDataRoot = Split-Path -Parent $PSScriptRoot
$StoreDir = Join-Path $MyDataRoot "data\crdb"
$CertsDir = Join-Path $MyDataRoot "certs\cockroach"

New-Item -ItemType Directory -Force -Path $StoreDir | Out-Null

$Candidates = @(
    (Join-Path $PSScriptRoot "cockroach.exe"),
    (Join-Path $MyDataRoot "bin\cockroach.exe")
)

$Cmd = Get-Command cockroach -ErrorAction SilentlyContinue
if ($Cmd) {
    $Candidates += $Cmd.Source
}

$CockroachExe = $Candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $CockroachExe) {
    throw "cockroach executable not found. Install CockroachDB and add it to PATH, or place cockroach.exe in MyData\\bin."
}

$SecureAvailable =
    (Test-Path (Join-Path $CertsDir "ca.crt")) -and
    (Test-Path (Join-Path $CertsDir "client.root.crt")) -and
    (Test-Path (Join-Path $CertsDir "client.root.key"))

$RunSecure = $SecureAvailable -and (-not $Insecure)

$Args = @(
    "start-single-node",
    "--store=$StoreDir",
    "--sql-addr=$SqlAddr",
    "--listen-addr=$ListenAddr",
    "--http-addr=$HttpAddr",
    "--max-sql-memory=25%",
    "--cache=25%"
)

if ($RunSecure) {
    $Args += "--certs-dir=$CertsDir"
} else {
    $Args += "--insecure"
}

if ($Foreground) {
    & $CockroachExe @Args
    exit $LASTEXITCODE
}

$Proc = Start-Process -FilePath $CockroachExe -ArgumentList $Args -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 1

Write-Output "cockroach_started pid=$($Proc.Id) secure=$RunSecure sql_addr=$SqlAddr"
Write-Output "DATABASE_URL example:"
if ($RunSecure) {
    $CertsPosix = $CertsDir -replace "\\", "/"
    Write-Output "cockroachdb+psycopg://root@127.0.0.1:26257/defaultdb?sslmode=verify-full&sslrootcert=$CertsPosix/ca.crt&sslcert=$CertsPosix/client.root.crt&sslkey=$CertsPosix/client.root.key"
} else {
    Write-Output "cockroachdb+psycopg://root@127.0.0.1:26257/defaultdb?sslmode=disable"
}

Test-NetConnection 127.0.0.1 -Port 26257 | Out-String | Write-Output
