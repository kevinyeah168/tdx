param(
    [string]$DataDir = "../data/workbench-real",
    [string]$TdxHome = "C:\new_tdx64",
    [switch]$SkipCatalogSync,
    [switch]$SkipFrontend,
    [switch]$RecreateVenv,
    [switch]$StartAfterSetup
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$BackendVenv = Join-Path $Backend ".venv\Scripts\python.exe"
$Requirements = Join-Path $Backend "requirements-dev.txt"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">> $Message" -ForegroundColor Cyan
}

function Resolve-PythonLauncher {
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($candidate -eq "py") {
            return @{ File = $cmd.Source; Args = @("-3") }
        }
        return @{ File = $cmd.Source; Args = @() }
    }
    return $null
}

function Invoke-Python {
    param(
        [string[]]$Arguments,
        [string]$WorkingDirectory = $Backend,
        [string]$PythonExe = ""
    )
    $exe = if ($PythonExe) { $PythonExe } else { $pythonLauncher.File }
    $prefix = if ($PythonExe) { @() } else { $pythonLauncher.Args }
    Push-Location $WorkingDirectory
    try {
        & $exe @($prefix + $Arguments)
        if ($LASTEXITCODE -ne 0) {
            throw "python exited with code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Resolve-DataDirPath {
    param([string]$RelativePath)
    Push-Location $Backend
    try {
        $parent = Split-Path -Parent $RelativePath
        if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        if (-not (Test-Path $RelativePath)) {
            New-Item -ItemType Directory -Force -Path $RelativePath | Out-Null
        }
        return (Resolve-Path $RelativePath).Path
    } finally {
        Pop-Location
    }
}

function Ensure-WorkbenchConfig {
    param(
        [string]$ResolvedDataDir,
        [string]$ResolvedTdxHome
    )

    $runDir = Join-Path $ResolvedDataDir "run"
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    $configPath = Join-Path $runDir "workbench_config.json"
    if (Test-Path $configPath) {
        Write-Host "  keep existing config: $configPath" -ForegroundColor DarkGray
        return
    }

    $tdxForJson = ($ResolvedTdxHome -replace '\\', '/')
    $payload = @{
        tdx_home = $tdxForJson
        collect_mode = "selective"
        archive_full_enabled = $false
    } | ConvertTo-Json
    Set-Content -Path $configPath -Value $payload -Encoding utf8
    Write-Host "  wrote $configPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "Market Workbench - first-time setup" -ForegroundColor Cyan
Write-Host "  Root:     $Root"
Write-Host "  Data:     $DataDir"
Write-Host "  TDX home: $TdxHome"
Write-Host ""

$pythonLauncher = Resolve-PythonLauncher
if (-not $pythonLauncher) {
    Write-Host "[ERROR] Python not found. Install Python 3.10+ and ensure 'py' or 'python' is on PATH." -ForegroundColor Red
    exit 1
}

if (-not $SkipFrontend) {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCmd) {
        Write-Host "[ERROR] npm.cmd not found. Install Node.js 18+ and reopen PowerShell." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path $Requirements)) {
    Write-Host "[ERROR] Missing $Requirements" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Write-Host "[ERROR] Missing frontend/package.json" -ForegroundColor Red
    exit 1
}

if ($RecreateVenv -and (Test-Path (Join-Path $Backend ".venv"))) {
    Write-Step "Remove existing Python venv"
    Remove-Item -Recurse -Force (Join-Path $Backend ".venv")
}

Write-Step "Create Python venv and install backend dependencies"
if (-not (Test-Path $BackendVenv)) {
    Invoke-Python -Arguments @("-m", "venv", ".venv")
}
Invoke-Python -PythonExe $BackendVenv -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python -PythonExe $BackendVenv -Arguments @("-m", "pip", "install", "-r", "requirements-dev.txt")

Write-Step "Verify critical Python packages"
Invoke-Python -PythonExe $BackendVenv -Arguments @(
    "-c",
    "import fastapi, uvicorn, curl_cffi; print('backend imports ok')"
)

if (-not $SkipFrontend) {
    Write-Step "Install frontend dependencies (npm install)"
    Push-Location $Frontend
    try {
        & npm.cmd install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

Write-Step "Prepare data directory and default config"
try {
    $resolvedDataDir = Resolve-DataDirPath $DataDir
} catch {
    Write-Host "[WARN] Could not resolve data dir yet: $DataDir" -ForegroundColor Yellow
    $resolvedDataDir = Join-Path $Root ($DataDir -replace '^\.\./', '')
    New-Item -ItemType Directory -Force -Path $resolvedDataDir | Out-Null
}

$resolvedTdxHome = $TdxHome
if (Test-Path $TdxHome) {
    $resolvedTdxHome = (Resolve-Path $TdxHome).Path
} else {
    Write-Host "[WARN] TDX home not found: $TdxHome" -ForegroundColor Yellow
    Write-Host "       Update data/run/workbench_config.json after installing TongDaXin." -ForegroundColor Yellow
}
Ensure-WorkbenchConfig -ResolvedDataDir $resolvedDataDir -ResolvedTdxHome $resolvedTdxHome

if (-not $SkipCatalogSync) {
    Write-Step "Sync sector/stock catalog from TDX (first run may take a minute)"
    if (-not (Test-Path $resolvedTdxHome)) {
        Write-Host "  skipped: TDX home does not exist" -ForegroundColor Yellow
    } else {
        Invoke-Python -PythonExe $BackendVenv -Arguments @(
            "-m", "workbench.collector.main",
            "--real",
            "--sync-catalog",
            "--data-dir", $DataDir,
            "--tdx-home", $resolvedTdxHome
        )
    }
} else {
    Write-Host ""
    Write-Host "  catalog sync skipped (-SkipCatalogSync)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start everything (API + UI + collectors):" -ForegroundColor White
Write-Host "       .\start-workbench-all-background.cmd" -ForegroundColor DarkGray
Write-Host "     or:" -ForegroundColor DarkGray
Write-Host "       .\scripts\start-workbench-all.ps1 -Background -TdxHome `"$resolvedTdxHome`" -DataDir `"$DataDir`"" -ForegroundColor DarkGray
Write-Host "  2. Open UI:" -ForegroundColor White
Write-Host "       http://127.0.0.1:5180/workbench.html" -ForegroundColor DarkGray
Write-Host "  3. Check collectors (combined + gray should both be online):" -ForegroundColor White
Write-Host "       http://127.0.0.1:8877/api/v1/health/detail" -ForegroundColor DarkGray
Write-Host "  4. Stop:" -ForegroundColor White
Write-Host "       .\stop-workbench-all.cmd" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Migrate history: copy data/workbench-real/ from another machine." -ForegroundColor DarkGray
Write-Host ""

if ($StartAfterSetup) {
    Write-Step "Launch workbench"
    & (Join-Path $PSScriptRoot "start-workbench-all.ps1") -Background -DataDir $DataDir -TdxHome $resolvedTdxHome
}
