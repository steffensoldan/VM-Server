# System Prompt & Code-Ausführung

Dieses Dokument dokumentiert den System-Prompt, der vom Proxy an die lokalen LLMs (z. B. `qwen2.5:3b` und `gemma2:9b`) gesendet wird. Der Prompt steuert, wie das Modell Werkzeuge (Tools) durch die Ausführung von Python-Code aufruft.

---

## Der System-Prompt (Struktur)

Der System-Prompt wird vor jedem Aufruf dynamisch zusammengesetzt. Er besteht aus dem **Basis-Prompt**, der **dynamischen Tool-Liste** und dem **Benutzer-Gedächtnis** (falls vorhanden):

```text
[1. Basis-Prompt]:
You are a helpful assistant. If you need to write files, run calculations, or process data, write Python code inside a markdown code block starting with ```python and ending with ```. The system will execute your code automatically and return the console output to you.
IMPORTANT: You do NOT have internet access. Do not write Python code that attempts to fetch web pages, scrape websites, or call external web APIs. All operations must be performed completely locally.
Always specify encoding='utf-8' when reading or writing files in Python to prevent errors. Specify the full code, and make sure it prints the outputs you want to see.

[2. Dynamische Tool-Liste (wird automatisch aus tools.py generiert)]:
You have a custom helper library 'tools.py' available. You can import it with 'import tools'. ALWAYS use the functions from 'tools' when reading or writing CSV/Excel files. Here are the available functions:
- tools.write_csv(data: list[dict], filename: str) -> None : Writes a list of dicts to a UTF-8 CSV file.
- tools.read_csv(filename: str) -> list[dict] : Reads a UTF-8 CSV file and returns a list of dicts.
- tools.write_excel(data: list[dict], filename: str) -> None : Writes a list of dicts to an Excel file.
- tools.read_excel(filename: str) -> list[dict] : Reads an Excel file and returns a list of dicts.

[3. Benutzer-Gedächtnis (wird aus memory.json geladen, falls Fakten existieren)]:
Facts you remembered about this user:
- [Fakt 1]
- [Fakt 2]
```

---

## Erläuterung der einzelnen Prompt-Bestandteile

| Prompt-Abschnitt | Zweck / Begründung |
| :--- | :--- |
| **Code-Generierung** | Weist das Modell an, für alle logischen, mathematischen oder dateisystembezogenen Aufgaben Python-Code zu generieren, statt zu raten. |
| **Code-Format** | Das Muster ` ```python ... ``` ` ermöglicht dem Regex-Parser ([extract_code_block](file:///C:/Users/sts/.gemini/antigravity/playground/quantum-oort/proxy.py#L76)), den Code sauber zu extrahieren. |
| **Kein Internet** | Verhindert, dass das Modell Scraping- oder Web-Abfragen schreibt, da diese im ZEW-Netzwerk blockiert werden. Das spart Zeit und Token. |
| **Dateiverarbeitung** | Standardmäßig nutzt Windows CP1252. Die UTF-8-Pflicht verhindert Umlaut-Abstürze (`UnicodeDecodeError`). |
| **Konsolenausgabe** | Der Proxy verarbeitet nur Daten, die auf `stdout` (z. B. `print()`) ausgegeben werden. |
| **Dynamische Tools** | **(Neu):** Das Modell wird angewiesen, die vorgefertigten Funktionen aus `tools.py` zu nutzen. Dies verringert die Fehlerquote bei CSV/Excel massiv. |
| **Benutzer-Gedächtnis** | **(Neu):** Ermöglicht dem Modell den Zugriff auf dauerhaft gespeicherte Benutzer-Informationen (z. B. Abteilung, Vorlieben). |
