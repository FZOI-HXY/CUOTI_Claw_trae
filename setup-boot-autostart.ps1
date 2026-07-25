# ======================================================
# DocFlow + Cloudflare Tunnel - Boot Auto-Start Installer
# Run this script as Administrator
# ======================================================

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[ERROR] Administrator privileges required!" -ForegroundColor Red
    Write-Host "Right-click PowerShell -> Run as Administrator, then run this script." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " DocFlow + Cloudflare Tunnel - Boot Auto-Start Setup" -ForegroundColor Cyan
Write-Host " (True boot trigger, no login required)" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Remove old Logon-trigger task
Write-Host "[1/5] Removing old Logon-trigger task..." -ForegroundColor Yellow
try {
    Unregister-ScheduledTask -TaskName "DocFlowCloudflareTunnel" -Confirm:$false -ErrorAction Stop
    Write-Host "  Old task removed." -ForegroundColor Green
} catch {
    Write-Host "  No old task found, continuing." -ForegroundColor Gray
}

# Step 2: Create Boot-trigger task with SYSTEM account
Write-Host ""
Write-Host "[2/5] Creating Boot-trigger task (SYSTEM, no login needed)..." -ForegroundColor Yellow

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument '-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\start-boot-tunnel.ps1"'

$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"  # 30 second delay after boot

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

try {
    Register-ScheduledTask `
        -TaskName "DocFlowBootTunnel" `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Start DocFlow backend and Cloudflare Tunnel at boot (no login required)" `
        -Force
    Write-Host "  Boot task created successfully!" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 3: Verify task
Write-Host ""
Write-Host "[3/5] Verifying task..." -ForegroundColor Yellow
$task = Get-ScheduledTask -TaskName "DocFlowBootTunnel"
Write-Host "  Task Name:    $($task.TaskName)" -ForegroundColor White
Write-Host "  State:        $($task.State)" -ForegroundColor White
Write-Host "  Trigger:      $($task.Triggers[0].CimClass.CimClassName)" -ForegroundColor White
Write-Host "  Run As:       $($task.Principal.UserId)" -ForegroundColor White
Write-Host "  Logon Type:   $($task.Principal.LogonType)" -ForegroundColor White
Write-Host "  Delay:        $($task.Triggers[0].Delay)" -ForegroundColor White

# Step 4: Verify config files exist
Write-Host ""
Write-Host "[4/5] Verifying config files..." -ForegroundColor Yellow
$configFile = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\deploy\cloudflared\config.yml"
$startScript = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\start-boot-tunnel.ps1"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$credFile = "C:\Users\IDC\.cloudflared\e87e7ffb-0b1d-4d5e-ae1e-994440ede7cc.json"

$allOk = $true
foreach ($f in @($configFile, $startScript, $cloudflared, $credFile)) {
    if (Test-Path $f) {
        Write-Host "  [OK] $f" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $f" -ForegroundColor Red
        $allOk = $false
    }
}

# Step 5: Summary
Write-Host ""
Write-Host "[5/5] Summary" -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "  Setup Complete! All components verified." -ForegroundColor Green
} else {
    Write-Host "  WARNING: Some files missing. Check above." -ForegroundColor Red
}
Write-Host ""
Write-Host "  Boot Task:     DocFlowBootTunnel" -ForegroundColor White
Write-Host "  Trigger:       At system boot (30s delay)" -ForegroundColor White
Write-Host "  Run As:        SYSTEM (no login needed)" -ForegroundColor White
Write-Host "  Log File:      data\logs\boot-tunnel.log" -ForegroundColor White
Write-Host ""
Write-Host "  On next reboot, these start automatically:" -ForegroundColor White
Write-Host "    - DocFlow Windows Service (NSSM, Automatic)" -ForegroundColor White
Write-Host "    - Cloudflare Tunnel (via boot task)" -ForegroundColor White
Write-Host ""
Write-Host "  Public URL:    https://huxiaoyang.dpdns.org" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Press Enter to exit"
