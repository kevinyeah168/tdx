param(
    [string]$ApiHost = "127.0.0.1",
    [int]$ApiPort = 8877
)

$ErrorActionPreference = "Stop"
$response = Invoke-WebRequest -Uri "http://${ApiHost}:${ApiPort}/api/v1/health" -UseBasicParsing
if ($response.StatusCode -ne 200) {
    throw "workbench api health check failed"
}
Write-Output "workbench api ok"
