# DocFlow + Cloudflare Tunnel 鍚姩鑴氭湰
# 寮€鏈鸿嚜鍚紝鍚庡彴杩愯

$ErrorActionPreference = "SilentlyContinue"

# 绛夊緟缃戠粶灏辩华
Start-Sleep -Seconds 5

# 鍚姩 DocFlow 鍚庣鏈嶅姟锛堥€氳繃 Windows 鏈嶅姟锛屽鏋滃凡瀹夎锛?$svc = Get-Service DocFlow -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne "Running") {
    Start-Service DocFlow -ErrorAction SilentlyContinue
}

# 濡傛灉 DocFlow 鏈嶅姟涓嶅瓨鍦紝鐩存帴鍚姩 Python
if (-not $svc) {
    $python = "C:\Users\IDC\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\python.exe"
    $projectDir = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae"
    Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "apps.web.api.main:app", "--host", "0.0.0.0", "--port", "8500", "--log-level", "info" -WorkingDirectory $projectDir -WindowStyle Hidden
}

# 绛夊緟 DocFlow 鍚姩
Start-Sleep -Seconds 3

# 鍚姩 Cloudflare Tunnel
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$configFile = "C:\Users\IDC\.cloudflared\config.yml"
Start-Process -FilePath $cloudflared -ArgumentList "tunnel", "--config", $configFile, "run", "docflow" -WindowStyle Hidden
