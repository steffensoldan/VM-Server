## Aktueller Stand
Zuletzt bearbeitet: 2026-06-22 durch [Claude / Cowork]
Letzter abgeschlossener Schritt: Planungsdokument aktualisiert, Code-Erweiterung bereit
Nächster Schritt: proxy.py erweitern (Stirling-Subprocess + PDF-Befehle), watchdog.ps1 ergänzen
Offene Fragen / Blockaden: Java-Pfad auf Server prüfen; Stirling PDF JAR manuell deployen; API-Endpunkt PDF→Excel nach Deployment verifizieren

---

# Tasks: VM-Server + Stirling PDF Integration

## Abgeschlossen (Basis-System)

- [x] LiteLLM deaktiviert
- [x] proxy.py (FastAPI + Telegram-Bot) deployed
- [x] GitHub-Repo verknüpft
- [x] AutoGenProxy Scheduled Task konfiguriert
- [x] watchdog.ps1 mit AutoGenProxyWatchdog Task

## Vorbereitung (manuell, einmalig)

- [ ] Stirling PDF ZIP entpacken → JAR nach `C:\AI-Tools\Stirling-PDF\app\stirling-pdf.jar`
- [ ] Java-Version auf Server prüfen (`java -version` → mind. 17)

## Code-Erweiterung (dieser Sprint)

- [ ] `proxy.py` erweitern: Stirling-Subprocess-Management
- [ ] `proxy.py` erweitern: PDF-Telegram-Befehle
- [ ] `watchdog.ps1` erweitern: Port 8080 überwachen
- [ ] `requirements.txt` prüfen (httpx bereits vorhanden?)

## Deployment

- [ ] Änderungen committen und nach GitHub pushen
- [ ] Auf Server: `git -C C:\AI-Tools\VM-Server pull`
- [ ] AutoGenProxy Task neu starten
- [ ] JAR manuell deployen (nicht im Repo)

## Verifikation

- [ ] Stirling PDF startet als Subprocess (Task-Log prüfen)
- [ ] `GET http://localhost:8080/api/v1/info` → Versioninfo
- [ ] Web-UI: `http://sts-w-0001.zew.local:8080` im Browser erreichbar
- [ ] Telegram `/pdf-compress`: PDF senden → Ergebnis zurück
- [ ] Telegram `/pdf-toexcel`: PDF senden → Excel/CSV zurück
- [ ] API-Endpunkt für PDF→Excel aus `/api/v1/info` ablesen und ggf. in proxy.py korrigieren
- [ ] `walkthrough.md` nach erfolgreichem Deployment ausfüllen
