## Aktueller Stand
Zuletzt bearbeitet: 2026-06-22 durch [Claude / Cowork]
Letzter abgeschlossener Schritt: Stirling PDF Integration vollständig deployed und verifiziert (Proof of Concept)
Nächster Schritt: Produktivbetrieb, ggf. weitere PDF-Befehle oder LibreOffice-Installation für erweiterte Konvertierungen
Offene Fragen / Blockaden: LibreOffice nicht installiert → PDF→Word/HTML/Presentation deaktiviert

---

# Tasks: VM-Server + Stirling PDF Integration

## Abgeschlossen (Basis-System)

- [x] LiteLLM deaktiviert
- [x] proxy.py (FastAPI + Telegram-Bot) deployed
- [x] GitHub-Repo verknüpft
- [x] AutoGenProxy Scheduled Task konfiguriert
- [x] watchdog.ps1 mit AutoGenProxyWatchdog Task

## Abgeschlossen (Stirling PDF Sprint 2026-06-22)

- [x] Stirling PDF JAR v2.13.1 deployt → `C:\AI-Tools\Stirling-PDF\app\stirling-pdf.jar`
- [x] Java 25 (Microsoft OpenJDK) installiert via winget
- [x] proxy.py erweitert: Stirling-Subprocess-Management (`_find_java`, `stirling_starten`, Monitor-Loop)
- [x] proxy.py erweitert: PDF-Telegram-Befehle (`/pdf-compress`, `/pdf-merge`, `/pdf-split`, `/pdf-rotate`, `/pdf-topng`, `/pdf-toexcel`)
- [x] watchdog.ps1 erweitert: Port 8080 überwachen
- [x] API-Endpunkte für Stirling v2.13.1 korrigiert (3 von 6 Pfade waren veraltet)
- [x] Stirling startet als Subprocess (PID unter AI-Admin, Port 8080 aktiv)
- [x] Web-UI erreichbar: `http://sts-w-0001.zew.local:8080`
- [x] Telegram `/pdf-compress`: funktioniert ✓
- [x] Telegram `/pdf-toexcel`: funktioniert (HTTP 204 bei PDFs ohne Tabellen = erwartetes Verhalten)

## Offen / Optional

- [ ] LibreOffice installieren → aktiviert PDF→Word, PDF→HTML, PDF→Presentation, HTML→PDF, EML→PDF
- [ ] `/pdf-toexcel` mit tabellarischer PDF testen (vollständiger Funktionstest)
- [ ] walkthrough.md um Stirling-Abschnitt ergänzen (bei Bedarf)
