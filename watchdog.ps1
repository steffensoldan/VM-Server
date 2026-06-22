# Set working directory to the script's directory
$PSScriptRoot = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
if (-not $PSScriptRoot) { $PSScriptRoot = "C:\AI-Tools\VM-Server" }

# Load environment variables
$envFile = Join-Path $PSScriptRoot ".env"
$botToken = $null
$allowedUsers = $null

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -match "^([^=]+)=(.*)$") {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            if ($key -eq "TELEGRAM_BOT_TOKEN") { $botToken = $value }
            if ($key -eq "TELEGRAM_ALLOWED_USERS") { $allowedUsers = $value }
        }
    }
}

# Get first user ID for alerts
$chatId = $null
if ($allowedUsers) {
    $chatId = ($allowedUsers -split ",")[0].Trim()
}

function Send-TelegramAlert($message) {
    if ($botToken -and $chatId) {
        $url = "https://api.telegram.org/bot$botToken/sendMessage"
        $body = @{
            chat_id = $chatId
            text = "⚠️ [VM-Server Watchdog]: $message"
        } | ConvertTo-Json
        try {
            $response = Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec 10
        } catch {
            Write-Error "Failed to send Telegram alert: $($_.Exception.Message)"
        }
    }
}

# 1. Check & Restart OllamaService if down
$ollamaTask = Get-ScheduledTask -TaskName "OllamaService" -ErrorAction SilentlyContinue
if ($ollamaTask) {
    if ($ollamaTask.State -ne "Running") {
        Write-Host "OllamaService is not running. Starting..."
        Start-ScheduledTask -TaskName "OllamaService"
        Send-TelegramAlert "OllamaService wurde unerwartet gestoppt und neu gestartet."
    }
} else {
    Send-TelegramAlert "Aufgabe 'OllamaService' wurde auf dem Server nicht gefunden!"
}

# 2. Check & Restart AutoGenProxy if down (beinhaltet Stirling PDF Subprocess)
$proxyTask = Get-ScheduledTask -TaskName "AutoGenProxy" -ErrorAction SilentlyContinue
if ($proxyTask) {
    if ($proxyTask.State -ne "Running") {
        Write-Host "AutoGenProxy is not running. Starting..."
        Start-ScheduledTask -TaskName "AutoGenProxy"
        Send-TelegramAlert "AutoGenProxy wurde unerwartet gestoppt und neu gestartet."
    } else {
        # Check if Port 4000 is actually listening
        $portActive = Get-NetTCPConnection -LocalPort 4000 -ErrorAction SilentlyContinue
        if (-not $portActive) {
            Write-Host "AutoGenProxy task is running but Port 4000 is not listening. Restarting task..."
            Stop-ScheduledTask -TaskName "AutoGenProxy"
            Start-Sleep -Seconds 2
            Start-ScheduledTask -TaskName "AutoGenProxy"
            Send-TelegramAlert "AutoGenProxy lief, aber Port 4000 war nicht aktiv. Task wurde neu gestartet."
        }
    }
} else {
    Send-TelegramAlert "Aufgabe 'AutoGenProxy' wurde auf dem Server nicht gefunden!"
}

# 3. Stirling PDF (Port 8080) — läuft als Subprocess von AutoGenProxy
# Wenn Port 8080 fehlt, reicht AutoGenProxy-Neustart (der startet den Subprocess neu).
$stirlingJar = "C:\AI-Tools\Stirling-PDF\app\stirling-pdf.jar"
if (Test-Path $stirlingJar) {
    $port8080 = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
    if (-not $port8080) {
        Write-Host "Stirling PDF (Port 8080) nicht aktiv. AutoGenProxy wird neu gestartet..."
        Stop-ScheduledTask -TaskName "AutoGenProxy" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName "AutoGenProxy"
        Send-TelegramAlert "Stirling PDF (Port 8080) nicht erreichbar. AutoGenProxy neu gestartet."
    } else {
        Write-Host "Stirling PDF OK (Port 8080 aktiv)."
    }
} else {
    Write-Host "Stirling PDF JAR nicht vorhanden — Überwachung übersprungen."
}
