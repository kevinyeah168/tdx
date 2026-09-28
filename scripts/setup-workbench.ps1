param(
    [string]$DataDir = "../data/workbench-real",
    [string]$TdxHome = "C:\new_tdx64",
    [string]$PythonExe = "",
    [switch]$SkipCatalogSync,
    [switch]$SkipFrontend,
    [switch]$RecreateVenv,
    [switch]$StartAfterSetup
)

$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force | Out-Null

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

function Test-PythonExecutable {
    param([string]$File)

    if (-not $File -or -not (Test-Path $File)) {
        return $false
    }

    if ($File -match "WindowsApps") {
        return $false
    }

    & $File -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Resolve-PythonExe {
    param([string]$PreferredExe = "")

    if ($PreferredExe) {
        $preferred = $PreferredExe.Trim('"')
        if (Test-PythonExecutable -File $preferred) {
            return (Resolve-Path $preferred).Path
        }
        throw "Specified PythonExe is not usable: $preferred"
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $resolved = & $pyCmd.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) {
            $exe = ($resolved | Select-Object -Last 1).Trim()
            if (Test-PythonExecutable -File $exe) {
                return (Resolve-Path $exe).Path
            }
        }
    }

    $candidatePaths = New-Object System.Collections.Generic.List[string]
    foreach ($root in @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python",
        "$env:ProgramFiles"
    )) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $candidatePaths.Add($_.FullName) }
    }

    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $candidatePaths.Add($cmd.Source)
        }
    }

    foreach ($path in ($candidatePaths | Select-Object -Unique)) {
        if (Test-PythonExecutable -File $path) {
            return (Resolve-Path $path).Path
        }
    }

    return $null
}

function Resolve-NpmExe {
    foreach ($candidate in @("npm.cmd", "npm")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and (Test-Path $cmd.Source)) {
            return $cmd.Source
        }
    }

    $fallbackPaths = @(
        "$env:ProgramFiles\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd",
        "$env:LOCALAPPDATA\Programs\node\npm.cmd"
    )
    foreach ($path in $fallbackPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }

    if ($env:NVM_HOME -and (Test-Path "$env:NVM_HOME\npm.cmd")) {
        return "$env:NVM_HOME\npm.cmd"
    }

    return $null
}

function Invoke-Python {
    param(
        [string[]]$Arguments,
        [string]$WorkingDirectory = $Backend,
        [string]$Exe = $script:BasePythonExe
    )

    $displayCmd = "$Exe $($Arguments -join ' ')"
    Push-Location $WorkingDirectory
    try {
        & $Exe @Arguments
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
        if ($exitCode -ne 0) {
            throw "python exited with code ${exitCode}: $displayCmd"
        }
    } finally {
        Pop-Location
    }
}

function Install-EasyTdx {
    param([string]$Exe = $BackendVenv)

    $bundledWheel = Join-Path $Backend "vendor\easy_tdx-1.20.7-py3-none-any.whl"
    if (Test-Path $bundledWheel) {
        Write-Host "  install easy-tdx from bundled wheel" -ForegroundColor DarkGray
        Invoke-Python -Exe $Exe -Arguments @("-m", "pip", "install", $bundledWheel) -WorkingDirectory $Backend
        return
    }

    Write-Host "  bundled wheel missing, trying PyPI mirrors..." -ForegroundColor Yellow
    Invoke-PipInstall -Exe $Exe -Packages @("easy-tdx>=1.20.0")
}

function Invoke-PipInstall {
    param(
        [string]$Exe = $BackendVenv,
        [string[]]$Packages
    )

    $mirrors = @(
        @{ Label = "PyPI"; Url = "" },
        @{ Label = "Tsinghua"; Url = "https://pypi.tuna.tsinghua.edu.cn/simple" },
        @{ Label = "Aliyun"; Url = "https://mirrors.aliyun.com/pypi/simple/" }
    )

    foreach ($mirror in $mirrors) {
        $args = @("-m", "pip", "install") + $Packages
        if ($mirror.Url) {
            $args += @("-i", $mirror.Url)
        }
        Write-Host "  pip via $($mirror.Label): $($Packages -join ' ')" -ForegroundColor DarkGray
        try {
            Invoke-Python -Exe $Exe -Arguments $args -WorkingDirectory $Backend
            return
        } catch {
            Write-Host "  failed on $($mirror.Label)" -ForegroundColor Yellow
        }
    }

    throw "pip install failed for: $($Packages -join ' '). Check network or install Python 3.12 LTS (not 3.14 preview)."
}

function New-BackendVenv {
    param([string]$Exe = $script:BasePythonExe)

    if (Test-Path $BackendVenv) {
        return
    }

    Write-Host "  create venv with: $Exe -m venv .venv" -ForegroundColor DarkGray
    Invoke-Python -Exe $Exe -Arguments @("-m", "venv", ".venv")

    if (-not (Test-Path $BackendVenv)) {
        throw "venv was not created at $BackendVenv"
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

$script:BasePythonExe = Resolve-PythonExe -PreferredExe $PythonExe
if (-not $script:BasePythonExe) {
    Write-Host "[ERROR] Python 3.10+ not found, or only the Windows Store alias is available." -ForegroundColor Red
    Write-Host "  1. Install Python 3.12 LTS: winget install Python.Python.3.12" -ForegroundColor Yellow
    Write-Host "  2. Or download: https://www.python.org/downloads/ (check 'Add python.exe to PATH')" -ForegroundColor Yellow
    Write-Host "  3. Settings -> Apps -> Advanced app settings -> App execution aliases" -ForegroundColor Yellow
    Write-Host "     Turn OFF aliases for python.exe and python3.exe" -ForegroundColor Yellow
    Write-Host "  4. Manual override:" -ForegroundColor Yellow
    Write-Host "     .\scripts\setup-workbench.ps1 -PythonExe `"C:\Path\To\python.exe`"" -ForegroundColor DarkGray
    exit 1
}

$pythonVersion = (& $script:BasePythonExe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')" 2>$null | Select-Object -Last 1).Trim()
Write-Host "  Python:   $script:BasePythonExe ($pythonVersion)" -ForegroundColor DarkGray
if ($pythonVersion -match "rc|alpha|beta") {
    Write-Host "[WARN] Pre-release Python detected. Prefer Python 3.12 LTS for fewer dependency issues." -ForegroundColor Yellow
}

$npmExe = $null
if (-not $SkipFrontend) {
    $npmExe = Resolve-NpmExe
    if (-not $npmExe) {
        Write-Host "[ERROR] npm not found." -ForegroundColor Red
        Write-Host "  1. Install Node.js 18+ LTS: https://nodejs.org/" -ForegroundColor Yellow
        Write-Host "  2. Or run: winget install OpenJS.NodeJS.LTS" -ForegroundColor Yellow
        Write-Host "  3. Close this window, reopen PowerShell, then rerun setup-workbench.cmd" -ForegroundColor Yellow
        Write-Host "  4. Backend-only for now: .\scripts\setup-workbench.ps1 -SkipFrontend" -ForegroundColor DarkGray
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
New-BackendVenv -Exe $script:BasePythonExe
Invoke-PipInstall -Exe $BackendVenv -Packages @("--upgrade", "pip")
Install-EasyTdx -Exe $BackendVenv
Invoke-PipInstall -Exe $BackendVenv -Packages @("-r", "requirements-dev.txt")

Write-Step "Verify critical Python packages"
Invoke-Python -Exe $BackendVenv -Arguments @(
    "-c",
    "import fastapi, uvicorn, curl_cffi; print('backend imports ok')"
)

if (-not $SkipFrontend) {
    Write-Step "Install frontend dependencies (npm install)"
    Push-Location $Frontend
    try {
        & $npmExe install
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
        Invoke-Python -Exe $BackendVenv -Arguments @(
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
