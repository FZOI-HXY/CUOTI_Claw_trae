@echo off
chcp 65001 >nul 2>&1
title Fix Cloudflare Tunnel Service
color 0A

echo ======================================================
echo   Fix Cloudflare Tunnel Service
echo ======================================================
echo.

:: Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Administrator privileges required!
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo [OK] Administrator privileges verified
echo.

:: Try to stop and delete old services
echo [INFO] Cleaning up old services...
sc stop cloudflared >nul 2>&1
sc stop Cloudflared >nul 2>&1
timeout /t 2 /nobreak >nul
sc delete cloudflared >nul 2>&1
sc delete Cloudflared >nul 2>&1
timeout /t 2 /nobreak >nul

:: Grant SYSTEM user read access to the config directory
echo [INFO] Granting SYSTEM user access to config directory...
icacls "C:\Users\IDC\.cloudflared" /grant "SYSTEM:(OI)(CI)F" /T >nul 2>&1

echo [OK] Permissions granted
echo.

:: Use NSSM to create service with a NEW name to avoid conflicts
echo [INFO] Installing CloudflareTunnel service via NSSM...
set "CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "CONFIG_FILE=C:\Users\IDC\.cloudflared\config.yml"

nssm install CloudflareTunnel "%CLOUDFLARED%" tunnel --config "%CONFIG_FILE%" run
nssm set CloudflareTunnel AppDirectory "C:\Users\IDC\.cloudflared"
nssm set CloudflareTunnel AppStdout "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\data\logs\cloudflared-service.log"
nssm set CloudflareTunnel AppStderr "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\data\logs\cloudflared-service.log"
nssm set CloudflareTunnel AppRotateFiles 1
nssm set CloudflareTunnel AppRotateBytes 10485760
nssm set CloudflareTunnel Start SERVICE_AUTO_START
nssm set CloudflareTunnel Description "Cloudflare Tunnel for DocFlow - huxiaoyang.dpdns.org"

echo.
echo [OK] CloudflareTunnel service installed
echo.

:: Ensure DocFlow is running
echo [INFO] Checking DocFlow service...
sc query DocFlow | findstr "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Starting DocFlow service...
    sc start DocFlow
    timeout /t 3 /nobreak >nul
) else (
    echo [OK] DocFlow service is already running
)
echo.

:: Start CloudflareTunnel service
echo [INFO] Starting CloudflareTunnel service...
sc start CloudflareTunnel
echo.

:: Wait for tunnel to connect
echo [INFO] Waiting for tunnel to connect (15 seconds)...
timeout /t 15 /nobreak >nul

:: Verify
echo.
echo ======================================================
echo   Verification
echo ======================================================
echo.

echo CloudflareTunnel service status:
sc query CloudflareTunnel | findstr "STATE"
echo.

echo DocFlow service status:
sc query DocFlow | findstr "STATE"
echo.

echo Testing https://huxiaoyang.dpdns.org ...
curl -s -o nul -w "HTTP Status: %%{http_code}\n" https://huxiaoyang.dpdns.org
echo.

echo Testing API health check...
curl -s https://huxiaoyang.dpdns.org/api/health
echo.
echo.

echo ======================================================
echo   If HTTP Status is 200, everything is working!
echo.
echo   Services installed:
echo     - DocFlow         (auto-start, port 8500)
echo     - CloudflareTunnel (auto-start, public access)
echo.
echo   Public URL: https://huxiaoyang.dpdns.org
echo.
echo   Management:
echo     sc start CloudflareTunnel   / sc stop CloudflareTunnel
echo     sc start DocFlow            / sc stop DocFlow
echo ======================================================
pause
