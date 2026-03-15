[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) "admin.env"),
    [switch]$SkipRolloutWait
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "required_command_missing: $Name"
    }
}

function Read-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "env_file_not_found: $Path"
    }

    $map = @{}
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $s = [string]$line
        if ([string]::IsNullOrWhiteSpace($s)) { continue }
        $trim = $s.Trim()
        if ($trim.StartsWith("#")) { continue }
        if (-not $trim.Contains("=")) { continue }

        $parts = $trim.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()

        if ((($value.StartsWith('"')) -and $value.EndsWith('"')) -or (($value.StartsWith("'")) -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if (-not [string]::IsNullOrWhiteSpace($key)) {
            $map[$key] = $value
        }
    }
    return $map
}

function Get-OrDefault {
    param(
        [hashtable]$Map,
        [string]$Key,
        [string]$Default
    )
    if ($Map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace([string]$Map[$Key])) {
        return [string]$Map[$Key]
    }
    return $Default
}

function Require-Key {
    param(
        [hashtable]$Map,
        [string]$Key
    )
    if (-not $Map.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace([string]$Map[$Key])) {
        throw "required_env_key_missing: $Key"
    }
    return [string]$Map[$Key]
}

function To-Bool {
    param(
        [string]$Value,
        [bool]$Default = $false
    )

    $v = [string]$Value
    if ([string]::IsNullOrWhiteSpace($v)) {
        return $Default
    }

    $n = $v.Trim().ToLowerInvariant()
    if ($n -in @("1", "true", "yes", "y", "on")) { return $true }
    if ($n -in @("0", "false", "no", "n", "off")) { return $false }
    return $Default
}

function Render-Template {
    param(
        [string]$TemplatePath,
        [hashtable]$Tokens
    )

    $raw = Get-Content -Path $TemplatePath -Raw -Encoding UTF8
    foreach ($k in $Tokens.Keys) {
        $raw = $raw.Replace([string]$k, [string]$Tokens[$k])
    }
    return $raw
}

function Apply-RenderedTemplate {
    param(
        [string]$TemplatePath,
        [hashtable]$Tokens
    )

    $rendered = Render-Template -TemplatePath $TemplatePath -Tokens $Tokens
    $rendered | kubectl apply -f - | Out-Host
}

function Ensure-CertManagerInstalled {
    try {
        $null = kubectl get crd certificates.cert-manager.io -o name 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "cert_manager_crd_missing"
        }
    }
    catch {
        throw "cert_manager_not_installed_or_unreachable"
    }
}

Require-Command -Name "kubectl"

$cfg = Read-EnvFile -Path $EnvFile
$manifestRoot = Join-Path (Split-Path -Parent $PSScriptRoot) "manifests"

$namespace = Get-OrDefault -Map $cfg -Key "NAMESPACE" -Default "mydata-prod"
$image = Require-Key -Map $cfg -Key "IMAGE"
$hostname = Require-Key -Map $cfg -Key "HOSTNAME"

$replicas = [int](Get-OrDefault -Map $cfg -Key "REPLICAS" -Default "3")
$workers = [int](Get-OrDefault -Map $cfg -Key "UVICORN_WORKERS" -Default "3")
$hpaMin = [int](Get-OrDefault -Map $cfg -Key "HPA_MIN_REPLICAS" -Default "3")
$hpaMax = [int](Get-OrDefault -Map $cfg -Key "HPA_MAX_REPLICAS" -Default "40")

if ($replicas -lt 1) { throw "invalid_REPLICAS" }
if ($workers -lt 1) { throw "invalid_UVICORN_WORKERS" }
if ($hpaMin -lt 1 -or $hpaMax -lt $hpaMin) { throw "invalid_HPA_min_max" }

$ingressClass = Get-OrDefault -Map $cfg -Key "INGRESS_CLASS" -Default "nginx"
$tlsSecretName = Get-OrDefault -Map $cfg -Key "TLS_SECRET_NAME" -Default "mydata-api-tls"

$certManagerEnabled = To-Bool -Value (Get-OrDefault -Map $cfg -Key "CERT_MANAGER_ENABLED" -Default "true") -Default $true
$certManagerCreateIssuer = To-Bool -Value (Get-OrDefault -Map $cfg -Key "CERT_MANAGER_CREATE_ISSUER" -Default "true") -Default $true
$certIssuerKind = Get-OrDefault -Map $cfg -Key "CERT_MANAGER_ISSUER_KIND" -Default "Issuer"
$certIssuerName = Get-OrDefault -Map $cfg -Key "CERT_MANAGER_ISSUER_NAME" -Default "mydata-letsencrypt"
$certManagerEmail = Get-OrDefault -Map $cfg -Key "CERT_MANAGER_EMAIL" -Default ""
$certManagerAcmeServer = Get-OrDefault -Map $cfg -Key "CERT_MANAGER_ACME_SERVER" -Default "https://acme-v02.api.letsencrypt.org/directory"

if ($certManagerEnabled) {
    if ($certIssuerKind -notin @("Issuer", "ClusterIssuer")) {
        throw "invalid_CERT_MANAGER_ISSUER_KIND"
    }
    if ($certManagerCreateIssuer -and [string]::IsNullOrWhiteSpace($certManagerEmail)) {
        throw "required_env_key_missing: CERT_MANAGER_EMAIL"
    }
}

$tokens = @{
    "__NAMESPACE__" = $namespace
    "__IMAGE__" = $image
    "__HOSTNAME__" = $hostname
    "__REPLICAS__" = [string]$replicas
    "__UVICORN_WORKERS__" = [string]$workers
    "__HPA_MIN_REPLICAS__" = [string]$hpaMin
    "__HPA_MAX_REPLICAS__" = [string]$hpaMax
    "__INGRESS_CLASS__" = $ingressClass
    "__TLS_SECRET_NAME__" = $tlsSecretName
    "__CERT_ISSUER_KIND__" = $certIssuerKind
    "__CERT_MANAGER_ISSUER_NAME__" = $certIssuerName
    "__CERT_MANAGER_EMAIL__" = $certManagerEmail
    "__CERT_MANAGER_ACME_SERVER__" = $certManagerAcmeServer
}

$requiredSecretKeys = @(
    "DATABASE_URL",
    "JWT_SECRET",
    "STORAGE_GRANT_SECRET",
    "GUARD_BOT_SIGNING_MASTER_SECRET",
    "STORAGE_ENDPOINT",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY"
)

$secretData = @{}
foreach ($k in $requiredSecretKeys) {
    $secretData[$k] = Require-Key -Map $cfg -Key $k
}

$optionalSecretKeys = @(
    "SUPERADMIN_STEP_UP_TOTP_SECRET",
    "SECURITY_ALERT_WEBHOOK_URL"
)
foreach ($k in $optionalSecretKeys) {
    if ($cfg.ContainsKey($k) -and -not [string]::IsNullOrWhiteSpace([string]$cfg[$k])) {
        $secretData[$k] = [string]$cfg[$k]
    }
}

$corsDefault = "https://app.$hostname"
$configData = @{
    "APP_ENV" = "prod"
    "AUTH_DEV_TOKEN_ENABLED" = "false"
    "API_DOCS_ENABLED_IN_PROD" = "false"
    "SECURITY_ENFORCE_PROD_CHECKS" = "true"
    "CORS_ALLOW_ORIGINS" = (Get-OrDefault -Map $cfg -Key "CORS_ALLOW_ORIGINS" -Default $corsDefault)
    "CORS_ALLOW_CREDENTIALS" = (Get-OrDefault -Map $cfg -Key "CORS_ALLOW_CREDENTIALS" -Default "false")
    "SENSITIVE_RATE_LIMIT_PER_MINUTE" = (Get-OrDefault -Map $cfg -Key "SENSITIVE_RATE_LIMIT_PER_MINUTE" -Default "60")
    "SENSITIVE_GET_RATE_LIMIT_PER_MINUTE" = (Get-OrDefault -Map $cfg -Key "SENSITIVE_GET_RATE_LIMIT_PER_MINUTE" -Default "1200")
    "CORE_ENTITLEMENT_CACHE_TTL_SECONDS" = (Get-OrDefault -Map $cfg -Key "CORE_ENTITLEMENT_CACHE_TTL_SECONDS" -Default "15")
    "CORE_ENTITLEMENT_CACHE_MAX_ENTRIES" = (Get-OrDefault -Map $cfg -Key "CORE_ENTITLEMENT_CACHE_MAX_ENTRIES" -Default "20000")
    "DB_POOL_SIZE" = (Get-OrDefault -Map $cfg -Key "DB_POOL_SIZE" -Default "80")
    "DB_MAX_OVERFLOW" = (Get-OrDefault -Map $cfg -Key "DB_MAX_OVERFLOW" -Default "160")
    "DB_POOL_TIMEOUT_SECONDS" = (Get-OrDefault -Map $cfg -Key "DB_POOL_TIMEOUT_SECONDS" -Default "30")
    "DB_POOL_RECYCLE_SECONDS" = (Get-OrDefault -Map $cfg -Key "DB_POOL_RECYCLE_SECONDS" -Default "1800")
    "GUARD_BOT_SIGNATURE_REQUIRED" = (Get-OrDefault -Map $cfg -Key "GUARD_BOT_SIGNATURE_REQUIRED" -Default "true")
    "STORAGE_PROVIDER" = (Get-OrDefault -Map $cfg -Key "STORAGE_PROVIDER" -Default "minio")
    "STORAGE_BUCKET_VERIFICATION" = (Get-OrDefault -Map $cfg -Key "STORAGE_BUCKET_VERIFICATION" -Default "mydata-verification")
    "STORAGE_BUCKET_PUBLIC_ASSETS" = (Get-OrDefault -Map $cfg -Key "STORAGE_BUCKET_PUBLIC_ASSETS" -Default "mydata-public-assets")
    "STORAGE_REGION" = (Get-OrDefault -Map $cfg -Key "STORAGE_REGION" -Default "us-east-1")
    "STORAGE_SECURE" = (Get-OrDefault -Map $cfg -Key "STORAGE_SECURE" -Default "true")
    "STORAGE_PRESIGN_TTL_SECONDS" = (Get-OrDefault -Map $cfg -Key "STORAGE_PRESIGN_TTL_SECONDS" -Default "900")
    "STORAGE_DOWNLOAD_PRESIGN_TTL_SECONDS" = (Get-OrDefault -Map $cfg -Key "STORAGE_DOWNLOAD_PRESIGN_TTL_SECONDS" -Default "120")
    "LICENSE_ISSUANCE_DEFAULT_MODE" = (Get-OrDefault -Map $cfg -Key "LICENSE_ISSUANCE_DEFAULT_MODE" -Default "SEMI")
}

Write-Host "[1/6] Apply namespace"
Apply-RenderedTemplate -TemplatePath (Join-Path $manifestRoot "namespace.yaml") -Tokens $tokens

Write-Host "[2/6] TLS (cert-manager optional)"
if ($certManagerEnabled) {
    Ensure-CertManagerInstalled

    if ($certManagerCreateIssuer) {
        if ($certIssuerKind -eq "Issuer") {
            Apply-RenderedTemplate -TemplatePath (Join-Path $manifestRoot "issuer.yaml") -Tokens $tokens
        }
        else {
            Apply-RenderedTemplate -TemplatePath (Join-Path $manifestRoot "clusterissuer.yaml") -Tokens $tokens
        }
    }

    Apply-RenderedTemplate -TemplatePath (Join-Path $manifestRoot "certificate.yaml") -Tokens $tokens
}
else {
    Write-Host "  cert-manager disabled (CERT_MANAGER_ENABLED=false). Expect existing TLS secret: $tlsSecretName"
}

Write-Host "[3/6] Upsert secrets"
$secretArgs = @("create", "secret", "generic", "mydata-api-secrets", "-n", $namespace, "--dry-run=client", "-o", "yaml")
foreach ($entry in $secretData.GetEnumerator()) {
    $secretArgs += "--from-literal=$($entry.Key)=$($entry.Value)"
}
$secretYaml = & kubectl @secretArgs
$secretYaml | kubectl apply -f - | Out-Host

Write-Host "[4/6] Upsert configmap"
$configArgs = @("create", "configmap", "mydata-api-config", "-n", $namespace, "--dry-run=client", "-o", "yaml")
foreach ($entry in $configData.GetEnumerator()) {
    $configArgs += "--from-literal=$($entry.Key)=$($entry.Value)"
}
$configYaml = & kubectl @configArgs
$configYaml | kubectl apply -f - | Out-Host

Write-Host "[5/6] Apply workload manifests"
$applyOrder = @(
    "deployment.yaml",
    "service.yaml",
    "ingress.yaml",
    "hpa.yaml",
    "pdb.yaml"
)
foreach ($name in $applyOrder) {
    Apply-RenderedTemplate -TemplatePath (Join-Path $manifestRoot $name) -Tokens $tokens
}

Write-Host "[6/6] Verify rollout"
if (-not $SkipRolloutWait) {
    kubectl -n $namespace rollout status deployment/mydata-api --timeout=300s | Out-Host
}
kubectl -n $namespace get deployment mydata-api | Out-Host
kubectl -n $namespace get pods -l app=mydata-api | Out-Host
kubectl -n $namespace get svc mydata-api | Out-Host
kubectl -n $namespace get hpa mydata-api | Out-Host
kubectl -n $namespace get ingress mydata-api | Out-Host

if ($certManagerEnabled) {
    kubectl -n $namespace get certificate mydata-api-cert 2>$null | Out-Host
}

Write-Host "Done. API host: https://$hostname"