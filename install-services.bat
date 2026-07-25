@echo off
chcp 65001 >nul 2>&1
title DocFlow + Cloudflare Tunnel Service Installer
color 0A

echo ======================================================
echo   DocFlow + Cloudflare Tunnel Service Installer
echo ======================================================
echo.
echo This script requires Administrator privileges.
echo.

:: Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Administrator privileges required!
    echo.
    echo Please right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

color 0A
echo [OK] Administrator privileges verified
echo.

:: Set paths
set "PYTHON=C:\Users\IDC\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\python.exe"
set "PROJECT_DIR=C:\Users\IDC\CodeBuddy\CUOTIClaw_trae"
set "LOG_DIR=%PROJECT_DIR%\data\logs"
set "CLOUDFLARED=C:\Program Files (x86)\cloudflared\cloudflared.exe"

:: Ensure log directory exists
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ======================================================
echo   1/3  Configure DocFlow Service
echo ======================================================
echo.

:: Remove existing service if present
sc query DocFlow >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] DocFlow service already exists, stopping and removing...
    sc stop DocFlow >nul 2>&1
    timeout /t 2 /nobreak >nul
    sc delete DocFlow >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo [INFO] Installing DocFlow service...
nssm install DocFlow "%PYTHON%" "-m uvicorn apps.web.api.main:app --host 0.0.0.0 --port 8500 --log-level info"
nssm set DocFlow AppDirectory "%PROJECT_DIR%"
nssm set DocFlow AppStdout "%LOG_DIR%\docflow-service.log"
nssm set DocFlow AppStderr "%LOG_DIR%\docflow-service.log"
nssm set DocFlow AppRotateFiles 1
nssm set DocFlow AppRotateBytes 10485760
nssm set DocFlow Start SERVICE_AUTO_START
nssm set DocFlow Description "DocFlow - AI Document Recognition and Management System"

echo.
echo [OK] DocFlow service installed
echo.

echo ======================================================
echo   2/3  Configure Cloudflare Tunnel Service
echo ======================================================
echo.

sc query cloudflared >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] cloudflared service already exists, skipping
) else (
    echo [INFO] Installing cloudflared service...
    "%CLOUDFLARED%" service install
)

echo.
echo [OK] cloudflared service installed
echo.

echo ======================================================
echo   3/3  Start Services
echo ======================================================
echo.

echo [INFO] Starting DocFlow service...
sc start DocFlow
timeout /t 3 /nobreak >nul

echo [INFO] Starting cloudflared service...
sc start cloudflared
timeout /t 3 /nobreak >nul

echo.
echo ======================================================
echo   Installation Complete! Service Status:
echo ======================================================
echo.
sc query DocFlow
echo.
sc query cloudflared
echo.

echo ======================================================
echo   Verify Public Access
echo ======================================================
echo.
echo Testing https://huxiaoyang.dpdns.org ...
curl -s -o nul -w "HTTP Status: %%{http_code}\n" https://huxiaoyang.dpdns.org
echo.
echo Testing API health check...
curl -s https://huxiaoyang.dpdns.org/api/health
echo.
echo.

echo ======================================================
echo   Service Management Commands:
echo ======================================================
echo.
echo   Start:     sc start DocFlow    /  sc start cloudflared
echo   Stop:      sc stop DocFlow     /  sc stop cloudflared
echo   Status:    sc query DocFlow    /  sc query cloudflared
echo   Delete:    sc delete DocFlow   /  sc delete cloudflared
echo.
echo   Log file:  %LOG_DIR%\docflow-service.log
echo.
echo   Public URL:  https://huxiaoyang.dpdns.org
echo.
echo ======================================================
pause
