# Futures Options SD Dashboard - Docker Dual Service Manager
param (
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "update", "live", "demo", "test", "run-all", "logs", "status", "build")]
    [string]$Command = "start"
)

$ErrorActionPreference = "Stop"

switch ($Command) {
    "start" {
        Write-Host ""
        Write-Host "[*] Starting Dual Services: Dashboard Web + Auto-Updater Daemon..." -ForegroundColor Cyan
        docker compose up -d dashboard updater
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "  [OK] 1. Web Dashboard is LIVE : http://localhost:8050" -ForegroundColor Green
        Write-Host "  [OK] 2. Auto-Updater Daemon   : ACTIVE (Background Sync)" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "  >> View logs:  .\docker-run.ps1 logs" -ForegroundColor Yellow
        Write-Host "  >> Stop:       .\docker-run.ps1 stop" -ForegroundColor Yellow
        Write-Host "  >> Quant Demo: .\docker-run.ps1 demo" -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""
    }
    "stop" {
        Write-Host "[*] Stopping dashboard and updater containers..." -ForegroundColor Yellow
        docker compose down
        Write-Host "[OK] Stopped successfully." -ForegroundColor Green
    }
    "restart" {
        Write-Host "[*] Restarting both services..." -ForegroundColor Cyan
        docker compose restart dashboard updater
        Write-Host "[OK] Restarted." -ForegroundColor Green
    }
    "build" {
        Write-Host "[*] Rebuilding Docker image..." -ForegroundColor Cyan
        docker compose build --no-cache dashboard
        Write-Host "[OK] Build complete." -ForegroundColor Green
    }
    "update" {
        Write-Host "[*] Manually triggering update_dashboard.py inside container..." -ForegroundColor Cyan
        docker compose run --rm pipeline python update_dashboard.py
        Write-Host "[OK] Dashboard data updated!" -ForegroundColor Green
    }
    "live" {
        Write-Host "[*] Manually triggering live_feed.py inside container..." -ForegroundColor Cyan
        docker compose run --rm pipeline python live_feed.py
        Write-Host "[OK] Live feed snapshot updated!" -ForegroundColor Green
    }
    "demo" {
        Write-Host "[*] Running Institutional Terminal Demo inside container..." -ForegroundColor Cyan
        docker compose run --rm pipeline python demo_institutional_terminal.py
    }
    "test" {
        Write-Host "[*] Running test suite inside container..." -ForegroundColor Cyan
        docker compose run --rm pipeline python -m unittest discover tests
    }
    "run-all" {
        Write-Host "[*] Running run_all.py inside container..." -ForegroundColor Cyan
        docker compose run --rm pipeline python run_all.py
    }
    "logs" {
        docker compose logs -f dashboard updater
    }
    "status" {
        docker compose ps
    }
}
