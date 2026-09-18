param(
    [string]$DataDir = "../data/workbench-real",
    [string]$TdxHome = "C:\new_tdx64",
    [string]$BindHost = "127.0.0.1",
    [int]$ApiPort = 8877,
    [int]$FrontendPort = 5180,
    [switch]$SkipCollector,
    [switch]$Background
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$BackendVenv = Join-Path $Backend ".venv\Scripts\python.exe"
$FrontendPkg = Join-Path $Frontend "package.json"
$RunDir = Join-Path $Root "data\run\workbench"

function Resolve-DataDirPath {
    param([string]$RelativePath)
    Push-Location $Backend
    try {
        return (Resolve-Path $RelativePath).Path
    } finally {
        Pop-Location
    }
}

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-ListenerPid {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Wait-WorkbenchReady {
    param(
        [int]$ApiPort,
        [int]$FrontendPort,
        [int]$TimeoutSec = 25
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $apiOk = $false
        $uiOk = $false
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/api/v1/health" -UseBasicParsing -TimeoutSec 2
            $apiOk = $response.StatusCode -eq 200
        } catch {}
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/workbench.html" -UseBasicParsing -TimeoutSec 2
            $uiOk = $response.StatusCode -eq 200
        } catch {}
        if ($apiOk -and $uiOk) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Update-ListenerPidFile {
    param(
        [string]$Name,
        [int]$Port
    )

    $listenerPid = Get-ListenerPid -Port $Port
    if ($listenerPid) {
        $listenerPid | Set-Content (Join-Path $RunDir "$Name.pid") -Encoding ascii
    }
}

function Wait-ListenerPid {
    param(
        [int]$Port,
        [int]$TimeoutSec = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $listenerPid = Get-ListenerPid -Port $Port
        if ($listenerPid) { return $listenerPid }
        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Start-WorkbenchHiddenProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [hashtable]$Environment = @{}
    )

    $logOut = Join-Path $RunDir "$Name.out.log"
    $logErr = Join-Path $RunDir "$Name.err.log"
    $pidFile = Join-Path $RunDir "$Name.pid"

    if (Test-Path $pidFile) {
        $existingPid = (Get-Content $pidFile -Raw).Trim()
        if ($existingPid -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) {
            throw "$Name already running (pid=$existingPid). Run scripts/stop-workbench-all.ps1 first."
        }
    }

    foreach ($key in $Environment.Keys) {
        Set-Item -Path "env:$key" -Value $Environment[$key]
    }

    $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError $logErr `
        -PassThru

    $proc.Id | Set-Content $pidFile -Encoding ascii
    return [pscustomobject]@{
        Name = $Name
        Pid  = $proc.Id
        Log  = $logOut
    }
}

if (-not (Test-Path $BackendVenv)) {
    Write-Host "[ERROR] Python venv not found: $BackendVenv" -ForegroundColor Red
    Write-Host "  cd backend" -ForegroundColor DarkGray
    Write-Host "  python -m venv .venv" -ForegroundColor DarkGray
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt" -ForegroundColor DarkGray
    exit 1
}

if (-not (Test-Path $FrontendPkg)) {
    Write-Host "[ERROR] Missing frontend/package.json" -ForegroundColor Red
    exit 1
}

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host "[ERROR] npm.cmd not found in PATH." -ForegroundColor Red
    exit 1
}

try {
    $resolvedDataDir = Resolve-DataDirPath $DataDir
} catch {
    Write-Host "[WARN] Data directory not found: $DataDir" -ForegroundColor Yellow
    Write-Host "       Collector will create it on first run." -ForegroundColor Yellow
    $resolvedDataDir = (Join-Path $Root ($DataDir -replace '^\.\./', ''))
}

# Drop leftover collectors before launch (duplicate writers corrupt hot DBs).
foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
    $cmd = $proc.CommandLine
    if ($cmd -and ($cmd -like "*workbench.collector.main*")) {
        $null = Start-Process -FilePath "taskkill.exe" -ArgumentList @("/PID", "$($proc.ProcessId)", "/T", "/F") `
            -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue
        Write-Host "  cleaned leftover collector pid=$($proc.ProcessId)" -ForegroundColor DarkGray
    }
}
foreach ($runPath in @((Join-Path $Root "data\workbench-real\run"), $RunDir)) {
    if (-not (Test-Path $runPath)) { continue }
    Get-ChildItem -Path $runPath -Filter "collector-*.lock" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    foreach ($staleRole in @("collector-hot.json", "collector-archive.json")) {
        $stalePath = Join-Path $runPath $staleRole
        if (Test-Path $stalePath) {
            Remove-Item $stalePath -Force -ErrorAction SilentlyContinue
        }
    }
}

if (Test-PortListening -Port $ApiPort) {
    Write-Host "[ERROR] API port $ApiPort is already in use." -ForegroundColor Red
    Write-Host "        Workbench may already be running." -ForegroundColor Yellow
    Write-Host "        Open http://${BindHost}:${FrontendPort}/workbench.html" -ForegroundColor Yellow
    Write-Host "        Or run scripts/stop-workbench-all.ps1 first." -ForegroundColor DarkGray
    exit 1
}

if (Test-PortListening -Port $FrontendPort) {
    Write-Host "[ERROR] Frontend port $FrontendPort is already in use." -ForegroundColor Red
    Write-Host "        Run scripts/stop-workbench-all.ps1 first." -ForegroundColor DarkGray
    exit 1
}

Write-Host ""
Write-Host "Market Workbench - one-click start" -ForegroundColor Cyan
Write-Host "  Mode:      $(if ($Background) { 'background (no windows)' } else { 'foreground (PowerShell windows)' })"
Write-Host "  Data:      $resolvedDataDir"
Write-Host "  API:       http://${BindHost}:${ApiPort}"
Write-Host "  UI:        http://${BindHost}:${FrontendPort}/workbench.html"
if (-not $SkipCollector) {
    Write-Host "  Collector: yuntu (combined) + gray (East Money, separate process)"
} else {
    Write-Host "  Collector: skipped (-SkipCollector)"
}
Write-Host ""

if ($Background) {
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

    $started = @()
    $started += Start-WorkbenchHiddenProcess -Name "api" -FilePath $BackendVenv `
        -ArgumentList @("-m", "uvicorn", "workbench.api.main:app", "--host", $BindHost, "--port", "$ApiPort") `
        -WorkingDirectory $Backend `
        -Environment @{ WORKBENCH_DATA_DIR = $resolvedDataDir }

    $started += Start-WorkbenchHiddenProcess -Name "frontend" -FilePath $npmCmd.Source `
        -ArgumentList @("run", "dev:workbench", "--", "--port", "$FrontendPort", "--host", "127.0.0.1") `
        -WorkingDirectory $Frontend

    if (-not $SkipCollector) {
        $started += Start-WorkbenchHiddenProcess -Name "collector" -FilePath $BackendVenv `
            -ArgumentList @(
                "-u", "-m", "workbench.collector.main", "--real", "--serve", "--mode", "combined",
                "--data-dir", $DataDir, "--tdx-home", $TdxHome
            ) `
            -WorkingDirectory $Backend

        $started += Start-WorkbenchHiddenProcess -Name "collector-gray" -FilePath $BackendVenv `
            -ArgumentList @(
                "-u", "-m", "workbench.collector.main", "--real", "--serve", "--mode", "gray",
                "--data-dir", $DataDir, "--tdx-home", $TdxHome
            ) `
            -WorkingDirectory $Backend
    }

    Write-Host "Waiting for API and UI..." -ForegroundColor DarkGray
    if (-not (Wait-WorkbenchReady -ApiPort $ApiPort -FrontendPort $FrontendPort)) {
        Write-Host "[ERROR] Workbench did not become ready in time." -ForegroundColor Red
        Write-Host "        Check logs in: $RunDir" -ForegroundColor Yellow
        foreach ($item in $started) {
            Write-Host "  $($item.Name): $($item.Log)" -ForegroundColor DarkGray
        }
        exit 1
    }

    $apiListener = Wait-ListenerPid -Port $ApiPort
    if ($apiListener) {
        $apiListener | Set-Content (Join-Path $RunDir "api.pid") -Encoding ascii
    } else {
        Update-ListenerPidFile -Name "api" -Port $ApiPort
    }

    $frontendListener = Wait-ListenerPid -Port $FrontendPort
    if ($frontendListener) {
        $frontendListener | Set-Content (Join-Path $RunDir "frontend.pid") -Encoding ascii
    } else {
        Update-ListenerPidFile -Name "frontend" -Port $FrontendPort
    }

    Write-Host "Started $($started.Count) background process(es):" -ForegroundColor Green
    foreach ($item in $started) {
        Write-Host "  $($item.Name) pid=$($item.Pid)  log=$($item.Log)"
    }
    Write-Host ""
    Write-Host "Open:  http://${BindHost}:${FrontendPort}/workbench.html" -ForegroundColor Green
    Write-Host "Stop:  stop-workbench-all.cmd" -ForegroundColor DarkGray
    Write-Host "Logs:  $RunDir" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

$psExe = (Get-Command powershell.exe).Source
$apiScript = Join-Path $PSScriptRoot "start-workbench-api.ps1"
$frontendScript = Join-Path $PSScriptRoot "start-workbench-frontend.ps1"
$collectorScript = Join-Path $PSScriptRoot "start-workbench-collector.ps1"

Start-Process $psExe -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $apiScript,
    "-DataDir", $DataDir, "-BindHost", $BindHost, "-Port", $ApiPort
) -WorkingDirectory $Root

Start-Process $psExe -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $frontendScript,
    "-Port", $FrontendPort
) -WorkingDirectory $Root

if (-not $SkipCollector) {
    Start-Process $psExe -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $collectorScript,
        "-DataDir", $DataDir, "-TdxHome", $TdxHome
    ) -WorkingDirectory $Root

    Start-Process $psExe -ArgumentList @(
        "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start-workbench-collector-gray.ps1"),
        "-DataDir", $DataDir, "-TdxHome", $TdxHome
    ) -WorkingDirectory $Root
}

$windowCount = if ($SkipCollector) { 2 } else { 4 }
Write-Host "Started $windowCount PowerShell window(s). Close each window to stop that service." -ForegroundColor Green
Write-Host ""
