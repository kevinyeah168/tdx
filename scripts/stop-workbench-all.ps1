param(
    [int]$ApiPort = 8877,
    [int]$FrontendPort = 5180
)

$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "data\run\workbench"
$DataRunDir = Join-Path $Root "data\workbench-real\run"

function Stop-ProcessTree {
    param([int]$ProcessId, [string]$Label)

    if ($ProcessId -le 0) { return $false }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }

    $null = Start-Process -FilePath "taskkill.exe" -ArgumentList @("/PID", "$ProcessId", "/T", "/F") `
        -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue
    Write-Host "  $Label : stopped pid $ProcessId (tree)" -ForegroundColor Green
    return $true
}

function Get-ListenerPids {
    param([int]$Port)

    $pids = @()
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $connections) {
            $processId = [int]$conn.OwningProcess
            if ($processId -gt 0 -and $pids -notcontains $processId) {
                $pids += $processId
            }
        }
    } catch {
        $line = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING" | Select-Object -First 1
        if ($line) {
            $parts = ($line -split "\s+") | Where-Object { $_ -ne "" }
            $processId = [int]$parts[-1]
            if ($processId -gt 0) { $pids += $processId }
        }
    }
    return $pids
}

function Stop-ByPort {
    param([int]$Port, [string]$Label)

    $stopped = $false
    foreach ($processId in (Get-ListenerPids -Port $Port)) {
        if (Stop-ProcessTree -ProcessId $processId -Label $Label) {
            $stopped = $true
        }
    }
    return $stopped
}

function Remove-PidFile {
    param([string]$PidFile, [string]$Label)

    if (-not (Test-Path $PidFile)) {
        Write-Host "  $Label : no pid file" -ForegroundColor DarkGray
        return
    }

    $rawPid = (Get-Content $PidFile -Raw).Trim()
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    if ($rawPid) {
        Write-Host "  $Label : removed pid file ($rawPid)" -ForegroundColor DarkGray
    }
}

function Stop-WorkbenchOrphans {
    $patterns = @(
        "tdx-market-workbench",
        "workbench.collector.main",
        "workbench.api.main",
        "vite.workbench.config",
        "dev:workbench"
    )

    $stopped = 0
    foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
        $cmd = $proc.CommandLine
        if (-not $cmd) { continue }
        $matched = $false
        foreach ($pattern in $patterns) {
            if ($cmd -like "*$pattern*") {
                $matched = $true
                break
            }
        }
        if (-not $matched) { continue }
        if (Stop-ProcessTree -ProcessId ([int]$proc.ProcessId) -Label "orphan $($proc.Name)") {
            $stopped += 1
        }
    }
    return $stopped
}

function Test-PortListening {
    param([int]$Port)
    return (Get-ListenerPids -Port $Port).Count -gt 0
}

function Remove-LockFiles {
    param([string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    Get-ChildItem -Path $Dir -Filter "collector-*.lock" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "  lock : removed $($_.Name)" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Stopping Market Workbench background services..." -ForegroundColor Cyan

# 1) Kill listeners first (node/vite and uvicorn are often child processes)
Stop-ByPort -Port $FrontendPort -Label "frontend" | Out-Null
Stop-ByPort -Port $ApiPort -Label "api" | Out-Null

# 2) Clean pid files and try any stale pids with tree kill
if (Test-Path $RunDir) {
    foreach ($name in @("collector-hot", "collector-archive", "collector", "frontend", "api")) {
        $pidFile = Join-Path $RunDir "$name.pid"
        if (Test-Path $pidFile) {
            $rawPid = (Get-Content $pidFile -Raw).Trim()
            if ($rawPid -match '^\d+$') {
                Stop-ProcessTree -ProcessId ([int]$rawPid) -Label $name | Out-Null
            }
        }
        Remove-PidFile -PidFile $pidFile -Label $name
    }
}

# 3) Orphan sweep for npm/node/python wrappers
$orphans = Stop-WorkbenchOrphans
if ($orphans -gt 0) {
    Write-Host "  cleaned $orphans orphan process tree(s)" -ForegroundColor Green
}

Remove-LockFiles -Dir $RunDir
Remove-LockFiles -Dir $DataRunDir

Start-Sleep -Milliseconds 800

$frontendUp = Test-PortListening -Port $FrontendPort
$apiUp = Test-PortListening -Port $ApiPort

Write-Host ""
if ($frontendUp -or $apiUp) {
    Write-Host "[WARN] some services may still be running:" -ForegroundColor Yellow
    if ($frontendUp) { Write-Host "  - frontend still listening on $FrontendPort" -ForegroundColor Yellow }
    if ($apiUp) { Write-Host "  - api still listening on $ApiPort" -ForegroundColor Yellow }
    Write-Host "  try running this script again, or reboot." -ForegroundColor DarkGray
    exit 1
}

Write-Host "Done. Ports $FrontendPort and $ApiPort are free." -ForegroundColor Green
Write-Host "Refresh the browser - the page should no longer load." -ForegroundColor DarkGray
Write-Host ""
