param(
    [string]$DataDir = "../data/workbench-real",
    [string]$TdxHome = "C:\new_tdx64"
)

$ErrorActionPreference = "Stop"
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"
Set-Location $backend
.\.venv\Scripts\python.exe -m workbench.collector.main --real --serve --mode combined --data-dir $DataDir --tdx-home $TdxHome
