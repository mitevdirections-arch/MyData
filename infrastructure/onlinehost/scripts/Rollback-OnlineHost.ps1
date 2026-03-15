[CmdletBinding()]
param(
    [string]$Namespace = "mydata-prod"
)

$ErrorActionPreference = "Stop"

kubectl -n $Namespace rollout undo deployment/mydata-api
kubectl -n $Namespace rollout status deployment/mydata-api --timeout=180s
kubectl -n $Namespace get pods -l app=mydata-api