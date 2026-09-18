# Deprecated: archive collector was merged into combined mode.
# Use start-workbench-collector.ps1 or start-workbench-all-background.cmd instead.

$ErrorActionPreference = "Stop"
Write-Host "[deprecated] archive collector is no longer used." -ForegroundColor Yellow
Write-Host "           Run scripts/start-workbench-collector.ps1 (combined mode) instead." -ForegroundColor Yellow
exit 1
