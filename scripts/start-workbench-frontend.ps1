param(
    [int]$Port = 5180
)

$ErrorActionPreference = "Stop"
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend"
Set-Location $frontend
Write-Host "Workbench UI: http://127.0.0.1:$Port/workbench.html" -ForegroundColor Cyan
Write-Host "Legacy board stays on http://127.0.0.1:5178 (npm run dev)" -ForegroundColor DarkGray
npm run dev:workbench -- --port $Port --host 127.0.0.1
