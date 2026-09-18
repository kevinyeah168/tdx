param(
    [int]$FrontendPort = 5180,
    [int]$ApiPort = 8877,
    [string]$LocalHost = "127.0.0.1",
    [int]$ReadyTimeoutSec = 15,
    [ValidateSet("auto", "4", "6")]
    [string]$EdgeIpVersion = "4",
    [string[]]$DnsResolvers = @("1.1.1.1:53", "8.8.8.8:53")
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$StartAllScript = Join-Path $PSScriptRoot "start-workbench-all.ps1"

function Resolve-CloudflaredPath {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }

    throw @"
cloudflared not found.

Install once:
  winget install --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements

Then open a new PowerShell and run this script again.
"@
}

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-FrontendReady {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSec
    )

    $url = "http://${HostName}:${Port}/workbench.html"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-PortListening -Port $Port)) {
            Start-Sleep -Milliseconds 400
            continue
        }
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {}
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Test-DnsLookup {
    param(
        [string]$Name,
        [string]$Server = ""
    )

    try {
        if ($Server) {
            $result = Resolve-DnsName -Name $Name -Server $Server -ErrorAction Stop
        } else {
            $result = Resolve-DnsName -Name $Name -ErrorAction Stop
        }
        return [bool]$result
    } catch {
        return $false
    }
}

function Test-ApiHealth {
    param(
        [string]$HostName,
        [int]$Port
    )

    try {
        $response = Invoke-WebRequest -Uri "http://${HostName}:${Port}/api/v1/health" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$cloudflared = Resolve-CloudflaredPath
$localUrl = "http://${LocalHost}:${FrontendPort}"

Write-Host ""
Write-Host "Market Workbench - public demo tunnel" -ForegroundColor Cyan
Write-Host "  Local UI:  ${localUrl}/workbench.html"
Write-Host "  cloudflared: $cloudflared"
Write-Host ""

if (-not (Wait-FrontendReady -HostName $LocalHost -Port $FrontendPort -TimeoutSec $ReadyTimeoutSec)) {
    Write-Host "[ERROR] Frontend is not ready on port $FrontendPort." -ForegroundColor Red
    Write-Host ""
    Write-Host "Start workbench first, for example:" -ForegroundColor Yellow
    Write-Host "  .\scripts\start-workbench-all.ps1 -Background" -ForegroundColor DarkGray
    Write-Host "  .\scripts\start-workbench-all.ps1 -Background -SkipCollector" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Then verify locally:" -ForegroundColor Yellow
    Write-Host "  ${localUrl}/workbench.html" -ForegroundColor DarkGray
    exit 1
}

if (-not (Test-ApiHealth -HostName $LocalHost -Port $ApiPort)) {
    Write-Host "[WARN] API health check failed on port $ApiPort." -ForegroundColor Yellow
    Write-Host "       The page may load but charts/settings can fail until API is up." -ForegroundColor Yellow
    Write-Host "       Start API with: .\scripts\start-workbench-api.ps1" -ForegroundColor DarkGray
    Write-Host ""
}

Write-Host "Local workbench is ready." -ForegroundColor Green

$systemDnsOk = Test-DnsLookup -Name "region1.v2.argotunnel.com"
if (-not $systemDnsOk) {
    Write-Host ""
    Write-Host "[WARN] System DNS cannot resolve Cloudflare tunnel hosts (common on some routers)." -ForegroundColor Yellow
    Write-Host "       This script will use public DNS for cloudflared: $($DnsResolvers -join ', ')" -ForegroundColor Yellow
    if (-not (Test-DnsLookup -Name "region1.v2.argotunnel.com" -Server ($DnsResolvers[0] -replace ':53$', ''))) {
        Write-Host "[WARN] Public DNS check also failed. Tunnel may still work, but expect slower startup." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Security reminder:" -ForegroundColor Yellow
Write-Host "  - This link is public while the tunnel runs." -ForegroundColor Yellow
Write-Host "  - Workbench has no login; anyone with the URL can view and change settings." -ForegroundColor Yellow
Write-Host "  - Press Ctrl+C here when the demo ends." -ForegroundColor Yellow
Write-Host ""
Write-Host "Starting Cloudflare quick tunnel..." -ForegroundColor Cyan
Write-Host "  edge-ip-version: $EdgeIpVersion"
Write-Host "  dns-resolver:    $($DnsResolvers -join ', ') (env hint for cloudflared)"
Write-Host "Copy the https://....trycloudflare.com URL from the output below." -ForegroundColor DarkGray
Write-Host "A later ERR about 'DNS local resolver' is usually harmless if the URL already appeared." -ForegroundColor DarkGray
Write-Host ""

# Quick tunnel (--url) does not accept --dns-resolver-addrs; use env hint instead.
$env:TUNNEL_DNS_RESOLVER_ADDRS = ($DnsResolvers | Where-Object { $_ }) -join ","
$env:TUNNEL_EDGE_IP_VERSION = $EdgeIpVersion

& $cloudflared tunnel --url $localUrl --edge-ip-version $EdgeIpVersion
