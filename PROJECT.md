# Projekt-Metadaten: quantum-oort

Dieses Dokument beschreibt das Projekt deklarativ und tool-neutral. Es dient als Einstiegspunkt für jeden Agenten (Claude Code & Antigravity).

---

## 1. Projektübersicht

* **Ziel:** Schlanke, maßgeschneiderte Custom-Proxy-Architektur für Ollama-Modelle (FastAPI-Server) mit integrierter Python-Codeausführung (ReAct-Loop), Telegram-Bot-Integration und einem PowerShell-Watchdog zur Selbstheilung auf dem Windows-Server.
* **Status:** Produktion (Dienst läuft auf dem Windows-Server unter `C:\AI-Tools\VM-Server`)
* **Verantwortlicher Client:** Antigravity

---

## 2. Technologie-Stack

* **Core:** Python 3.10, FastAPI, Uvicorn, Ollama API, PowerShell (Watchdog)
* **Paketmanager:** pip
* **Abhängigkeiten:** `fastapi`, `uvicorn`, `ollama`, `httpx`, `paramiko`, `scp` (für Administration und Sync)

---

## 3. Testen & Verifizieren

Folgende Befehle werden zur Verifizierung der Codequalität und Lauffähigkeit verwendet:

* **Abhängigkeiten installieren:** `pip install -r requirements.txt` (Zusatzpakete für Bot/Watchdog: `pip install paramiko scp`)
* **Proxy-Server lokal starten:** `python -m uvicorn proxy:app --port 4000 --reload`
* **Watchdog-Skript ausführen (lokaler Test):** `powershell -ExecutionPolicy Bypass -File .\watchdog.ps1`
* **Ollama-Verbindung prüfen:** Der Proxy setzt eine lokale Instanz von Ollama auf Port 11434 voraus.

---

## 4. Wichtige Verzeichnisse & Strukturen

* `proxy.py`: Hauptskript. Enthält den FastAPI-Webservice (OpenAI-kompatibler Endpoint `/v1/chat/completions`) und die asynchrone Schleife für den Telegram-Bot.
* `tools.py`: Hilfsbibliothek für die Codeausführung (sicheres Lesen/Schreiben von Excel- und CSV-Dateien unter Windows).
* `watchdog.ps1`: PowerShell-Watchdog-Dienst. Überwacht Port 4000 und startet Ollama/Proxy bei Abstürzen neu.
* `Dokumentation/`: Enthält den technischen Walkthrough (`walkthrough.md`) und Spezifikationen.
