# Walkthrough: Schlanke Custom-Proxy-Architektur & Git-Deployment

Wir haben die Umstellung auf die vereinfachte, robuste Custom-Proxy-Architektur erfolgreich abgeschlossen. Das komplexe AutoGen-Framework und der LiteLLM-Übersetzungslayer wurden vollständig entfernt. Das System ist nun minimal, wartungsfrei und extrem stabil.

---

## 1. Umgesetzte Änderungen

### Infrastruktur-Vereinfachung (Server)
- **LiteLLM abgeschaltet:** Der Dienst `LiteLLMService` wurde dauerhaft gestoppt und deaktiviert. Port 4001 ist frei, Ressourcen wurden freigegeben.
- **Git auf dem Server installiert:** Git wurde systemweit auf dem Windows-Server installiert, um das Klonen und automatische Aktualisieren über GitHub zu ermöglichen.

### Codebase & Versionierung
- **Lokale Vorbereitung:** Die Dateien `proxy.py` und `requirements.txt` wurden im lokalen Verzeichnis erstellt und versioniert.
- **GitHub Master-Repository:** Die Codebase wurde in Ihr GitHub-Repository **[VM-Server](https://github.com/steffensoldan/VM-Server)** hochgeladen.
- **Server Deployment:** Das Repository wurde auf dem Server unter `C:\AI-Tools\VM-Server` geklont.
- **Task-Aktualisierung:** Die Windows-Aufgabe `AutoGenProxy` wurde neu konfiguriert, damit sie das bereinigte Skript direkt aus dem Git-Ordner startet.

---

## 2. Der neue Custom-Proxy (`proxy.py`)
Das Skript hat ca. 120 Zeilen und benötigt keine schweren Frameworks mehr. Es erledigt folgende Aufgaben:
- **Direktverbindung:** Kommuniziert direkt mit dem Ollama-Server auf Port 11434.
- **Regex-Codeausführung:** Sucht nach normalen Python-Markdownblöcken (` ```python ... ``` `). Wenn ein Block gefunden wird, wird er per nativem Subprozess (`subprocess.run`) ausgeführt und das Ergebnis zurück an das Modell gestreamt.
- **UTF-8 standardmäßig:** Durch Setzen von `os.environ["PYTHONUTF8"] = "1"` laufen alle ausgeführten Codes standardmäßig in UTF-8. Das verhindert UnicodeDecodeErrors (wie bei Umlauten) unter Windows.
- **Token-Messung:** Ermittelt bei jedem Turn die Prompt- und Completion-Tokens von Ollama und gibt diese sauber strukturiert an den Webchat zurück.

---

## 3. Verifikationsergebnisse

Wir haben die neue Architektur getestet, indem wir über den Proxy eine Anfrage an `gemma2:9b` geschickt haben, die eine CSV-Datei mit den Leibniz-Instituten in Baden-Württemberg (inklusive Umlaute) erstellt, einliest und das Ergebnis auswertet.

### Test-Ergebnis (Task-Log):
```text
--- TESTING MODEL: gemma2:9b ---
Currently flying....

That's great! The code successfully created the CSV file, saved the data with correct umlauts, and then read it back to display the information. 

Is there anything else I can help you with regarding Leibniz Institutes or working with CSV files?

* Sort the institutes by name or location?
* Create a different type of output...

Usage info: {'prompt_tokens': 957, 'completion_tokens': 632, 'total_tokens': 1589}
[DONE]
Duration: 266.65 seconds
```

- **Umlaut-Verhalten:** Keine UnicodeDecodeErrors mehr! Die CSV wurde erfolgreich mit Umlauten geschrieben und gelesen.
- **Token-Erfassung:** Die Token (957 prompt, 632 completion, 1589 total) wurden erfolgreich gemessen und zurückgegeben.
- **Stabilität:** Der Code lief über 3 Iterationen hinweg fehlerfrei (ReAct-Loop), ohne sich bei der JSON-Generierung zu verschlucken.

---

## 4. Zukünftiger Workflow für Aktualisierungen

Da das System nun dreistufig aufgebaut ist, können Sie Updates wie folgt einspielen:
1. **Lokal bearbeiten:** Sie ändern z. B. das Standardmodell in der Datei `proxy.py` lokal auf Ihrem PC.
2. **GitHub Push:** Sie committen und pushen die Änderung in Ihr GitHub-Repository.
3. **Server Pull & Neustart:** Sie verbinden sich mit dem Server und führen in der Eingabeaufforderung / PowerShell aus:
   ```cmd
   git -C C:\AI-Tools\VM-Server pull
   schtasks /end /tn AutoGenProxy
   schtasks /run /tn AutoGenProxy
   ```

---

## 5. Telegram-Bot Integration & Konfiguration

Der Telegram-Bot wurde direkt asynchron in den Proxy integriert. Er läuft im selben Prozess wie der FastAPI-Webservice, sodass keine separate Windows-Aufgabe benötigt wird.

### Einrichtungsschritte:

1. **Bot erstellen:**
   - Suchen Sie `@BotFather` in Telegram und senden Sie `/newbot`.
   - Folgen Sie den Anweisungen, um einen Namen und Benutzernamen festzulegen.
   - Kopieren Sie das generierte **HTTP API-Token** (z. B. `123456789:ABCdefGh...`).

2. **Token auf dem Server hinterlegen:**
   - Erstellen oder bearbeiten Sie die Datei `C:\AI-Tools\VM-Server\.env` auf dem Server.
   - Fügen Sie Ihr Token hinzu:
     ```env
     TELEGRAM_BOT_TOKEN=Ihr_Telegram_Token_Hier
     ```

3. **Dienst neu starten:**
   - Führen Sie auf dem Server folgende Befehle aus:
     ```cmd
     schtasks /end /tn AutoGenProxy
     schtasks /run /tn AutoGenProxy
     ```

4. **Sicherheit / Chat-ID autorisieren (Whitelisting):**
   - Starten Sie den Chat mit Ihrem neuen Bot in Telegram und senden Sie `/start` (oder eine beliebige Nachricht).
   - Der Bot wird den Zugriff verweigern und Ihnen Ihre persönliche **Chat-ID** anzeigen (z. B. `987654321`).
   - Fügen Sie diese ID in der Datei `.env` auf dem Server hinzu:
     ```env
     TELEGRAM_BOT_TOKEN=Ihr_Telegram_Token_Hier
     TELEGRAM_ALLOWED_USERS=987654321
     ```
     *(Mehrere IDs können mit Komma getrennt werden: `123456789,987654321`)*
   - Starten Sie den Dienst erneut über `schtasks` neu. Nun ist der Bot für Sie einsatzbereit!

---

## 6. Spezielle Chat-Befehle (Telegram)

Wir haben eine Reihe nützlicher Befehle direkt im Telegram-Bot implementiert. Diese werden vom Proxy abgefangen und sofort ausgeführt, ohne dass Rechenzeit bei Ollama verbraucht wird:

* `/start` : Zeigt eine Willkommensnachricht und die Liste aller verfügbaren Befehle an.
* `/model [qwen|gemma|llama]` : Ermöglicht den schnellen Modellwechsel direkt im Chat.
  - `/model qwen` -> Aktiviert das schnelle `qwen2.5:3b` (Standard)
  - `/model gemma` -> Aktiviert das stärkere `gemma2:9b`
  - `/model llama` -> Aktiviert das kompakte `llama3.2:3b`
* `/remember [Fakt]` : Speichert eine persönliche Information im Langzeitgedächtnis (gesichert in [memory.json](file:///C:/Users/sts/.gemini/antigravity/playground/quantum-oort/memory.json) auf dem Server).
  - *Beispiel:* `/remember Ich arbeite am ZEW in der IT-Abteilung`
  - Diese Information wird bei jeder nachfolgenden Anfrage dem LLM als Hintergrundkontext mitgegeben.
* `/forget` : Löscht alle über Ihre Chat-ID gespeicherten Fakten aus dem Gedächtnis des Bots.
* `/info` : Zeigt das aktuell ausgewählte Modell und alle über Sie im Gedächtnis gespeicherten Fakten an.

---

## 7. Lokale Werkzeug-Bibliothek (`tools.py`)

Um die Fehlerquote bei der Generierung von Dateioperationen (wie Excel/CSV) zu minimieren, haben wir eine Hilfsbibliothek [tools.py](file:///C:/Users/sts/.gemini/antigravity/playground/quantum-oort/tools.py) bereitgestellt.

Diese wird beim Start des Proxys automatisch in das Ausführungsverzeichnis (`C:\AI-Tools\AutoGen\coding\tools.py`) kopiert, sodass das LLM sie in generiertem Python-Code importieren kann.

### Verfügbare Funktionen in `tools.py`:

1. **`tools.write_csv(data: list[dict], filename: str) -> None`**
   - Schreibt eine Liste von Python-Dictionaries in eine UTF-8 CSV-Datei.
   - Verhindert Kodierungsfehler unter Windows durch automatisches Erzwingen von UTF-8.
2. **`tools.read_csv(filename: str) -> list[dict]`**
   - Liest eine UTF-8 CSV-Datei und gibt sie als Liste von Dictionaries zurück.
3. **`tools.write_excel(data: list[dict], filename: str) -> None`**
   - Schreibt eine Liste von Dictionaries in eine Excel-Datei (nutzt `pandas` und `openpyxl`).
4. **`tools.read_excel(filename: str) -> list[dict]`**
   - Liest eine Excel-Datei und konvertiert sie zurück in eine Liste von Dictionaries (konvertiert `NaN` automatisch in Python-kompatible `None`-Werte).

Das Modell ist im System-Prompt angewiesen, für jeglichen Excel- oder CSV-Dateizugriff ausschließlich diese Funktionen zu verwenden. Das reduziert die Codegröße auf 2–3 Zeilen und vermeidet Umlaut-Fehler komplett.



---

## 8. Monitoring & Watchdog-Dienst (Selbstheilung)

Um die Hochverfügbarkeit der Dienste zu garantieren und das standardmäßige 72-Stunden-Limit von Windows-Tasks zu umgehen, wurden folgende Mechanismen implementiert:

### Unbegrenzte Laufzeit der Hauptdienste
Das voreingestellte Limit von 3 Tagen (`ExecutionTimeLimit: PT72H`) für die Aufgaben `OllamaService` und `AutoGenProxy` wurde dauerhaft aufgehoben (`ExecutionTimeLimit: PT0S`). Die Tasks laufen nun unbegrenzt.

### Watchdog-Task (`AutoGenProxyWatchdog`)
Eine neue geplante Windows-Aufgabe `AutoGenProxyWatchdog` wurde auf dem Server registriert:
- **Dateipfad:** [watchdog.ps1](file:///C:/AI-Tools/VM-Server/watchdog.ps1) (lokal: [watchdog.ps1](file:///C:/Users/sts/Projekte-Antigravity/quantum-oort/watchdog.ps1))
- **Intervall:** Läuft alle 15 Minuten (und zusätzlich beim Systemstart).
- **Benutzerkonto:** Läuft unter dem Benutzer `AI-Admin`.
- **Aktionen:**
  1. Prüft, ob `OllamaService` läuft; falls nicht, wird dieser gestartet.
  2. Prüft, ob `AutoGenProxy` läuft; falls nicht, wird dieser gestartet.
  3. Prüft, ob Port `4000` aktiv ist; falls die Aufgabe zwar läuft, der Port aber nicht antwortet, wird der Proxy neu gestartet.
  4. Liest die Telegram-Zugangsdaten aus der Datei `C:\AI-Tools\VM-Server\.env` und sendet bei automatischen Restarts eine Warnung per Telegram an die erste hinterlegte Chat-ID.
