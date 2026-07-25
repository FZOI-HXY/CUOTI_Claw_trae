@echo off
chcp 65001 >nul 2>&1
echo ======================================================
echo  DocFlow + Cloudflare Tunnel - Boot Auto-Start Setup
echo  (True boot trigger, no login required)
echo ======================================================
echo.

:: Check admin privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Administrator privileges required!
    echo Right-click this file and select "Run as administrator"
    pause
    exit /b 1
)

echo [1/4] Removing old Logon-trigger task...
schtasks /delete /tn "DocFlowCloudflareTunnel" /f >nul 2>&1
if exist "DocFlowCloudflareTunnel" (
    echo     Old task removed.
) else (
    echo     No old task found, continuing.
)
echo.

echo [2/4] Creating Boot-trigger task (SYSTEM, no login needed)...
:: Create the task XML for boot trigger with SYSTEM account
set "TASK_XML=<?xml version="1.0" encoding="UTF-16"?>^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>^<RegistrationInfo^>^<Description^>Start DocFlow backend and Cloudflare Tunnel at boot (no login required)^</Description^>^</RegistrationInfo^>^<Triggers^>^<BootTrigger^>^<Enabled^>true^</Enabled^>^<Delay^>PT30S^</Delay^>^</BootTrigger^>^</Triggers^>^<Principals^>^<Principal id="Author"^>^<UserId^>S-1-5-18^</UserId^>^<RunLevel^>HighestAvailable^</RunLevel^>^</Principal^>^</Principals^>^<Settings^>^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>^<AllowHardTerminate^>true^</AllowHardTerminate^>^<StartWhenAvailable^>true^</StartWhenAvailable^>^<RunOnlyIfNetworkAvailable^>true^</RunOnlyIfNetworkAvailable^>^<AllowStartOnDemand^>true^</AllowStartOnDemand^>^<Enabled^>true^</Enabled^>^<Hidden^>false^</Hidden^>^<RunOnlyIdle^>false^</RunOnlyIdle^>^<WakeToRun^>true^</WakeToRun^>^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>^<Priority^>7^</Priority^>^</Settings^>^<Actions Context="Author"^>^<Exec^>^<Command^>powershell.exe^</Command^>^<Arguments^>-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\start-boot-tunnel.ps1"^</Arguments^>^</Exec^>^</Actions^>^</Task^>"

:: Write XML to temp file and register
set "TEMP_XML=%TEMP%\docflow_boot_task.xml"
powershell -Command "[System.IO.File]::WriteAllText('%TEMP_XML%', '%TASK_XML%', [System.Text.Encoding]::Unicode)"

schtasks /create /tn "DocFlowBootTunnel" /xml "%TEMP_XML%" /f
if %errorLevel% neq 0 (
    echo [ERROR] Failed to create boot task!
    pause
    exit /b 1
)
echo     Boot task created successfully.
echo.

echo [3/4] Verifying task...
schtasks /query /tn "DocFlowBootTunnel" /v /fo list | findstr /i "TaskName Status Run As User Trigger"
echo.

echo [4/4] Done!
echo.
echo ======================================================
echo  Setup Complete!
echo ======================================================
echo.
echo  Task Name:    DocFlowBootTunnel
echo  Trigger:      At system boot (30s delay)
echo  Run As:       SYSTEM (no login needed)
echo  Action:       start-boot-tunnel.ps1
echo.
echo  Next boot will auto-start:
echo    - DocFlow Windows Service (NSSM, Automatic)
echo    - Cloudflare Tunnel (via this task)
echo.
echo  Public URL: https://huxiaoyang.dpdns.org
echo.
pause
