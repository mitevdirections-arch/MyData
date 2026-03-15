[CmdletBinding()]
param(
    [string]$Namespace = "mydata-prod"
)

$ErrorActionPreference = "Stop"

kubectl -n $Namespace get deployment mydata-api
kubectl -n $Namespace get pods -l app=mydata-api
kubectl -n $Namespace get svc mydata-api
kubectl -n $Namespace get ingress mydata-api
kubectl -n $Namespace get hpa mydata-api
kubectl -n $Namespace get certificate 2>$null
kubectl -n $Namespace get certificaterequest 2>$null
kubectl -n $Namespace rollout status deployment/mydata-api --timeout=120s