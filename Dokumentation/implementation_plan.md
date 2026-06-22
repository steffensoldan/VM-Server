# Implementation Plan: VM-Server + Stirling PDF Integration

Dieses Dokument beschreibt die Erweiterung des bestehenden `proxy.py` um lokale PDF-Verarbeitung via Stirling PDF. Die Grundarchitektur (FastAPI + Telegram-Bot-Loop im selben Prozess) bleibt unverändert.

## User Review Required

> [!IMPORTANT]
> - **Keine neuen Scheduled Tasks**: Stirling PDF läuft als Subprocess von `proxy.py`. Nur `AutoGenProxy` bleibt der einzige Task.
> - **JAR nicht im Git-Repo**: `C:\AI-Tools\Stirling-PDF\app\stirling-pdf.jar` wird manuell deployt (ZIP entpacken). Liegt im `.gitignore`.
> - **Telegram ≠ DSGVO-sicher**: PDF-Befehle über Telegram nur für nicht-personenbezogene Dokumente. Für DSGVO-sensitive Dokumente: Web-UI unter `http://sts-w-0001.zew.local:8080`.
> - **Java 17+ Voraussetzung**: Muss auf Server vorhanden sein.

---

## Architektur

```
AutoGenProxy (Scheduled Task, AI-Admin)
  └── proxy.py
        ├── FastAPI (Port 4000) — bestehend, unverändert
        ├── Telegram-Bot-Loop — erweitert um PDF-Befehle
        │     ├── /pdf-compress   → Stirling API POST /compress-pdf
        │     ├── /pdf-merge      → Stirling API POST /merge-pdfs
        │     ├── /pdf-split      → Stirling API POST /split-pdf
        │     ├── /pdf-rotate     → Stirling API POST /rotate-pdf
        │     ├── /pdf-toexcel    → Stirling API POST /pdf-csv (⚠ Endpunkt verifizieren)
        │     └── /pdf-topng      → Stirling API POST /pdf-img
        └── Stirling PDF Subprocess (Port 8080)
              └── java -jar C:\AI-Tools\Stirling-PDF\app\stirling-pdf.jar

Web-UI (intern, kein Telegram):
  Browser → http://sts-w-0001.zew.local:8080  (Stirling PDF built-in UI)
```

---

## Geänderte Dateien

| Datei | Art | Beschreibung |
|---|---|---|
| `proxy.py` | Erweiterung | Stirling-Subprocess + PDF-Telegram-Befehle |
| `watchdog.ps1` | Erweiterung | Port 8080 überwachen, Subprocess-Neustart |
| `requirements.txt` | unverändert | httpx bereits vorhanden |
| `Dokumentation/task.md` | Erweiterung | neue Aufgaben |

**Nicht geändert:** Bestehende LLM-Logik, `/model`, `/remember`, `/forget`, `/info`, `/tools`, ReAct-Loop.

---

## Proposed Changes

### 1. `proxy.py` — Neue Sektionen (anhängen, nichts überschreiben)

#### 1a. Konstanten (oben im Modul, nach den Imports)

```python
STIRLING_URL   = "http://localhost:8080"
STIRLING_JAR   = Path("C:/AI-Tools/Stirling-PDF/app/stirling-pdf.jar")
STIRLING_PORT  = 8080
```

#### 1b. Subprocess-Management (neue Funktionen)

```python
stirling_proc: subprocess.Popen | None = None

def stirling_verfuegbar() -> bool:
    """Prüft ob Stirling PDF auf Port 8080 antwortet."""

async def stirling_starten():
    """Startet Stirling PDF als Subprocess. Kein Fehler wenn JAR fehlt."""

async def stirling_monitor_loop():
    """Prüft alle 60s ob Stirling läuft; startet neu bei Absturz."""
```

#### 1c. PDF-API-Wrapper (neue Funktion)

```python
async def stirling_api(
    client: httpx.AsyncClient,
    endpunkt: str,
    dateien: list[tuple[str, bytes]],
    felder: dict | None = None
) -> bytes | None:
    """Schlanker Wrapper für alle Stirling-Endpunkte. Gibt Ergebnis-Bytes zurück."""
```

#### 1d. Telegram PDF-Handler (neue Funktionen)

```python
# Zustandsspeicher für mehrstufige Operationen (z.B. Merge)
pdf_zustand: dict[int, dict] = {}

async def handle_pdf_befehl(client, tg_url, chat_id, befehl, arg):
    """Verarbeitet /pdf-* Befehle. Setzt Zustand für Datei-Empfang."""

async def handle_pdf_datei(client, tg_url, chat_id, message, config):
    """Empfängt PDF, ruft Stirling API auf, sendet Ergebnis zurück."""
```

#### 1e. Einbindung in bestehende Handler

- `handle_telegram_command()`: `/pdf-*` Befehle an `handle_pdf_befehl()` delegieren
- `handle_telegram_message()`: Dokument-Nachrichten an `handle_pdf_datei()` prüfen
- `startup_event()`: `stirling_starten()` und `stirling_monitor_loop()` als Task

---

### 2. `watchdog.ps1` — Port 8080 ergänzen

Analog zu bestehendem Port-4000-Check:
```powershell
# Stirling PDF (Port 8080) — läuft als Subprocess von AutoGenProxy
$port8080 = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
if (-not $port8080) {
    # AutoGenProxy neu starten triggert Stirling-Subprocess-Neustart
    Stop-ScheduledTask -TaskName AutoGenProxy
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName AutoGenProxy
    Send-TelegramAlert "Stirling PDF (Port 8080) nicht aktiv. AutoGenProxy neu gestartet."
}
```

---

## Entwicklungsmodell & Risiken

> [!WARNING]
> **Server = Entwicklungs- und Produktivumgebung gleichzeitig.**
> Änderungen an `proxy.py` wirken sofort auf den laufenden Telegram-Bot. Es gibt kein Staging.

**Workflow:**
```
Cowork / Claude (editiert Dateien auf Server)
    → git add / commit / push (manuell via SSH)
    → GitHub (steffensoldan/VM-Server)
    → git pull auf lokaler Maschine (Synchronisierung)
```

**Schutzmaßnahmen:**
- Vor jeder Änderung committen — dann ist ein Rollback möglich: `git revert HEAD`
- Watchdog (`AutoGenProxyWatchdog`) startet den Dienst bei Absturz automatisch neu
- Bei kritischen Änderungen: Task manuell stoppen, testen, dann wieder starten

---

## Deployment-Schritte (einmalig, als AI-Admin)

### Firewall-Regel für Stirling PDF Web-UI
Damit der Browser im ZEW-Netz `http://sts-w-0001.zew.local:8080` erreicht:

```powershell
New-NetFirewallRule `
    -DisplayName "Stirling PDF Web-UI" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8080 `
    -RemoteAddress "192.168.0.0/16" `
    -Force
```

> `RemoteAddress` auf das ZEW-Subnetz einschränken — kein offener Port nach außen.

### JAR deployen
```powershell
Expand-Archive -Path "<Pfad-zur-ZIP>" -DestinationPath "C:\AI-Tools\Stirling-PDF\app"
# JAR umbenennen falls nötig:
# Rename-Item "C:\AI-Tools\Stirling-PDF\app\Stirling-PDF-*.jar" "stirling-pdf.jar"
```

### Git pull + Task-Neustart
```powershell
git -C C:\AI-Tools\VM-Server pull
schtasks /end /tn AutoGenProxy
schtasks /run /tn AutoGenProxy
```

---

## Offene Punkte (vor Deployment zu klären)

| Punkt | Status |
|---|---|
| Stirling PDF API-Endpunkt für PDF→Excel | ⚠ ungesichert — nach Deployment verifizieren (`GET /api/v1/info`) |
| Java-Pfad auf Server im PATH? | ⚠ offen — manuell prüfen |
| Stirling PDF Startzeit (typ. 10–15s) | → Bot wartet und meldet wenn nicht bereit |
| Telegram Dateilimit 50 MB | → im Bot abgefangen mit Fehlermeldung |

---

## Verification Plan

1. `proxy.py` startet ohne Fehler: Task-Log prüfen
2. Stirling PDF erreichbar: `Invoke-RestMethod http://localhost:8080/api/v1/info`
3. Telegram `/pdf-compress`: PDF senden → komprimiertes PDF zurück
4. Telegram `/pdf-toexcel`: PDF senden → CSV/Excel zurück (Endpunkt validieren)
5. Web-UI erreichbar: Browser auf `http://sts-w-0001.zew.local:8080`
