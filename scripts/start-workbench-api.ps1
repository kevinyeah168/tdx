param(
    [string]$DataDir = "../data",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8877
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
Set-Location $Backend
$env:WORKBENCH_DATA_DIR = (Resolve-Path $DataDir).Path
.\.venv\Scripts\python.exe -m uvicorn workbench.api.main:app --host $BindHost --port $Port
