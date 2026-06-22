# Deploy-Skript: VM-Server Stirling PDF Integration
# Commit, Push, Task-Neustart
Set-Location "C:\AI-Tools\VM-Server"

Write-Host "==> Git add..."
git add proxy.py watchdog.ps1 Dokumentation/implementation_plan.md Dokumentation/task.md Dokumentation/walkthrough.md

Write-Host "==> Git commit..."
git commit -m "feat: Stirling PDF Integration (Subprocess + PDF-Telegram-Befehle)"

Write-Host "==> Git push..."
git push

Write-Host "==> AutoGenProxy neu starten..."
schtasks /end /tn AutoGenProxy
Start-Sleep -Seconds 3
schtasks /run /tn AutoGenProxy

Write-Host "==> Fertig. Warte 10s auf Prozessstart..."
Start-Sleep -Seconds 10

Write-Host "==> Prozess-Check:"
Get-Process -Name python -ErrorAction SilentlyContinue | Select-Object Id, CPU, WS
