param(
  [string]$FoundationBase = "http://127.0.0.1:8110",
  [string]$OperationalBase = "http://127.0.0.1:8120",
  [int]$TimeoutSec = 8
)

function Get-OpenApiPaths {
  param([string]$BaseUrl)

  $res = Invoke-RestMethod -Method GET -Uri "$BaseUrl/openapi.json" -TimeoutSec $TimeoutSec
  if (-not $res.paths) { return @() }
  return @($res.paths.PSObject.Properties.Name)
}

$foundationPaths = Get-OpenApiPaths -BaseUrl $FoundationBase
$operationalPaths = Get-OpenApiPaths -BaseUrl $OperationalBase

$foundationHasOrders = $foundationPaths -contains "/orders"
$foundationHasMarketplace = $foundationPaths -contains "/marketplace/catalog"
$operationalHasOrders = $operationalPaths -contains "/orders"
$operationalHasMarketplace = $operationalPaths -contains "/marketplace/catalog"

$ok = (-not $foundationHasOrders) -and $foundationHasMarketplace -and $operationalHasOrders -and (-not $operationalHasMarketplace)

[pscustomobject]@{
  ok = $ok
  foundation = [pscustomobject]@{
    base = $FoundationBase
    paths_count = $foundationPaths.Count
    has_orders = $foundationHasOrders
    has_marketplace_catalog = $foundationHasMarketplace
  }
  operational = [pscustomobject]@{
    base = $OperationalBase
    paths_count = $operationalPaths.Count
    has_orders = $operationalHasOrders
    has_marketplace_catalog = $operationalHasMarketplace
  }
} | ConvertTo-Json -Depth 6

if (-not $ok) { exit 1 }
