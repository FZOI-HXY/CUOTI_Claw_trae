# ======================================================
# DocFlow + Cloudflare Tunnel - Boot Auto-Start Script
# Runs as SYSTEM at boot (no login required)
# ======================================================

$ErrorActionPreference = "SilentlyContinue"
$LogFile = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae\data\logs\boot-tunnel.log"
$ProjectDir = "C:\Users\IDC\CodeBuddy\CUOTIClaw_trae"
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$ConfigFile = "$ProjectDir\deploy\cloudflared\config.yml"

# Ensure log directory exists
$logDir = Split-Path $LogFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Log-Message {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Msg"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

Log-Message "========== Boot auto-start triggered =========="

# Step 1: Wait for network to be ready (boot delay already 30s, but be safe)
Log-Message "Waiting for network..."
$networkReady = $false
for ($i = 0; $i -lt 12; $i++) {
    $ping = Test-Connection -ComputerName "1.1.1.1" -Count 1 -Quiet
    if ($ping) {
        $networkReady = $true
        Log-Message "Network is ready."
        break
    }
    Start-Sleep -Seconds 5
}
if (-not $networkReady) {
    Log-Message "WARNING: Network not ready after 60s, proceeding anyway..."
}

# Step 2: Ensure DocFlow service is running
Log-Message "Checking DocFlow service..."
$svc = Get-Service DocFlow -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne "Running") {
        Log-Message "Starting DocFlow service..."
        Start-Service DocFlow -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
        $svc = Get-Service DocFlow
        Log-Message "DocFlow service status: $($svc.Status)"
    } else {
        Log-Message "DocFlow service already running."
    }
} else {
    Log-Message "DocFlow service not found, starting via uvicorn..."
    $python = "C:\Users\IDC\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\python\python.exe"
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "apps.web.api.main:app", "--host", "0.0.0.0", "--port", "8500", "--log-level", "info" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden
    Start-Sleep -Seconds 8
    Log-Message "DocFlow started via uvicorn."
}

# Step 3: Kill any orphaned cloudflared, then start fresh
# (SYSTEM has permission to kill any process)
$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($cf) {
    Log-Message "Found existing cloudflared (PID $($cf.Id)), killing to avoid conflicts..."
    $cf | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $cf2 = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($cf2) {
        Log-Message "WARNING: cloudflared still running after kill attempt"
    } else {
        Log-Message "Old cloudflared killed."
    }
}

# Start cloudflared
if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
    Log-Message "Starting cloudflared tunnel..."
    if (Test-Path $Cloudflared) {
        if (Test-Path $ConfigFile) {
            Log-Message "Using config: $ConfigFile"
            $cfLog = "$logDir\cloudflared-stderr.log"
            $cfOut = "$logDir\cloudflared-stdout.log"
            # Remove old logs
            Remove-Item $cfLog, $cfOut -ErrorAction SilentlyContinue
            $proc = Start-Process -FilePath $Cloudflared `
                -ArgumentList "tunnel", "--config", $ConfigFile, "run", "docflow" `
                -WindowStyle Hidden `
                -RedirectStandardError $cfLog `
                -RedirectStandardOutput $cfOut `
                -PassThru
            Log-Message "cloudflared started (PID $($proc.Id))."
        } else {
            Log-Message "ERROR: Config file not found: $ConfigFile"
        }
    } else {
        Log-Message "ERROR: cloudflared not found at: $Cloudflared"
    }
}

# Step 4: Wait and verify
Start-Sleep -Seconds 10
$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($cf) {
    Log-Message "cloudflared is running (PID $($cf.Id))."
} else {
    Log-Message "ERROR: cloudflared failed to start! Checking stderr log..."
    $cfLog = "$logDir\cloudflared-stderr.log"
    if (Test-Path $cfLog) {
        $errContent = Get-Content $cfLog -Raw
        Log-Message "STDERR: $errContent"
    } else {
        Log-Message "No stderr log found."
    }
    $cfOut = "$logDir\cloudflared-stdout.log"
    if (Test-Path $cfOut) {
        $outContent = Get-Content $cfOut -Raw
        Log-Message "STDOUT: $outContent"
    }
}

# Step 5: Verify public URL (optional, non-blocking)
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8500/api/health" -UseBasicParsing -TimeoutSec 10
    Log-Message "Local health check: $($response.StatusCode) OK"
} catch {
    Log-Message "WARNING: Local health check failed: $($_.Exception.Message)"
}

Log-Message "========== Boot auto-start complete =========="
