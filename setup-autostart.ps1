# DocFlow + Cloudflare Tunnel 开机自启计划任务
# 无需管理员权限，用户登录时自动启动

$ErrorActionPreference = "Continue"

Write-Host "=== DocFlow + Cloudflare Tunnel Auto-Start Setup ===" -ForegroundColor Green
Write-Host ""

# 1. 创建启动脚本
$startupScript = @'
# DocFlow + Cloudflare Tunnel 启动脚本
# 开机自启，后台运行

$ErrorActionPreference = "SilentlyContinue"

# 等待网络就绪
Start-Sleep -Seconds 5

# 启动 DocFlow 后端服务（通过 Windows 服务，如果已安装）
$svc = Get-Service DocFlow -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne "Running") {
    Start-Service DocFlow -ErrorAction SilentlyContinue
}

# 如果 DocFlow 服务不存在，直接启动 Python
if (-not $svc) {
    $python = "C:\Users\IDC\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\python.exe"
    $projectDir = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae"
    Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "apps.web.api.main:app", "--host", "0.0.0.0", "--port", "8500", "--log-level", "info" -WorkingDirectory $projectDir -WindowStyle Hidden
}

# 等待 DocFlow 启动
Start-Sleep -Seconds 3

# 启动 Cloudflare Tunnel
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$configFile = "C:\Users\IDC\.cloudflared\config.yml"
Start-Process -FilePath $cloudflared -ArgumentList "tunnel", "--config", $configFile, "run", "docflow" -WindowStyle Hidden
'@

$scriptPath = "$env:USERPROFILE\CodeBuddy\CUOTIClaw_trae\start-docflow-tunnel.ps1"
$startupScript | Out-File -FilePath $scriptPath -Encoding UTF8 -Force
Write-Host "[OK] Startup script created: $scriptPath" -ForegroundColor Green

# 2. 创建计划任务 - 用户登录时自动运行
$taskName = "DocFlowCloudflareTunnel"

# 先删除旧任务（如果存在）
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 创建任务
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "DocFlow + Cloudflare Tunnel auto-start on login" -Force

Write-Host "[OK] Scheduled task created: $taskName" -ForegroundColor Green
Write-Host ""

# 3. 验证
Write-Host "=== Verification ===" -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "[OK] Task registered successfully" -ForegroundColor Green
    Write-Host "  Task Name: $($task.TaskName)"
    Write-Host "  State: $($task.State)"
    Write-Host "  Trigger: At logon of user $env:USERNAME"
} else {
    Write-Host "[ERROR] Task not found" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "DocFlow service (Windows Service):"
$svc = Get-Service DocFlow -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "  Status: $($svc.Status), StartType: $($svc.StartType)" -ForegroundColor Green
} else {
    Write-Host "  Not installed (will use Python directly)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Cloudflare Tunnel:"
Write-Host "  Managed by: Scheduled Task '$taskName'" -ForegroundColor Green
Write-Host "  Trigger: Auto-start on user login" -ForegroundColor Green
Write-Host "  Config: C:\Users\IDC\.cloudflared\config.yml" -ForegroundColor Green
Write-Host ""
Write-Host "Public URL: https://huxiaoyang.dpdns.org" -ForegroundColor Cyan
Write-Host ""
Write-Host "Management commands:"
Write-Host "  Start now:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Stop:       Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "  Check:      Get-ScheduledTask -TaskName '$taskName'"
Write-Host ""
