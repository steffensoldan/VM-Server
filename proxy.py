import os
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

import asyncio
import json
import time
import sys
import re
import subprocess
import importlib
import inspect
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import ollama
import httpx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ollama_client = ollama.AsyncClient(host="http://localhost:11434")
DEFAULT_MODEL = "qwen2.5:3b"
telegram_models = {}

# ---------------------------------------------------------------------------
# Stirling PDF — Konfiguration
# ---------------------------------------------------------------------------
STIRLING_URL = "http://localhost:8080"
STIRLING_JAR = Path("C:/AI-Tools/Stirling-PDF/app/stirling-pdf.jar")

# Zustandsspeicher für mehrstufige PDF-Operationen (z.B. Merge)
# Struktur: {chat_id: {"op": str, "dateien": [(name, bytes)], "params": dict}}
pdf_zustand: dict = {}

# Laufender Stirling-PDF-Subprocess
_stirling_proc: subprocess.Popen | None = None

def load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

def is_user_allowed(chat_id: int) -> bool:
    allowed_users_str = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    if not allowed_users_str:
        return False
    allowed_ids = [int(x.strip()) for x in allowed_users_str.split(",") if x.strip().isdigit()]
    return chat_id in allowed_ids

def get_memory_for_chat(chat_id: str) -> list[str]:
    memory_path = Path(__file__).parent / "memory.json"
    if not memory_path.exists():
        return []
    try:
        data = json.loads(memory_path.read_text(encoding="utf-8"))
        return data.get(str(chat_id), [])
    except Exception:
        return []

def save_memory_for_chat(chat_id: str, fact: str):
    memory_path = Path(__file__).parent / "memory.json"
    data = {}
    if memory_path.exists():
        try:
            data = json.loads(memory_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    chat_id_str = str(chat_id)
    if chat_id_str not in data:
        data[chat_id_str] = []
    if fact not in data[chat_id_str]:
        data[chat_id_str].append(fact)
    memory_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def clear_memory_for_chat(chat_id: str):
    memory_path = Path(__file__).parent / "memory.json"
    if memory_path.exists():
        try:
            data = json.loads(memory_path.read_text(encoding="utf-8"))
            if str(chat_id) in data:
                del data[str(chat_id)]
            memory_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Stirling PDF — Subprocess-Management
# ---------------------------------------------------------------------------

def stirling_verfuegbar() -> bool:
    """Prüft ob Stirling PDF auf Port 8080 antwortet."""
    try:
        import socket
        with socket.create_connection(("localhost", 8080), timeout=2):
            return True
    except OSError:
        return False

async def stirling_starten():
    """Startet Stirling PDF als Hintergrund-Subprocess. Kein Fehler wenn JAR fehlt."""
    global _stirling_proc
    if not STIRLING_JAR.exists():
        print(f"Stirling PDF: JAR nicht gefunden unter {STIRLING_JAR}. PDF-Funktionen deaktiviert.")
        return
    if stirling_verfuegbar():
        print("Stirling PDF: läuft bereits auf Port 8080.")
        return
    _stirling_proc = subprocess.Popen(
        ["java", "-jar", str(STIRLING_JAR), f"--server.port=8080"],
        cwd=str(STIRLING_JAR.parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Stirling PDF: Subprocess gestartet (PID {_stirling_proc.pid}).")

async def stirling_monitor_loop():
    """Überwacht Stirling-Subprocess alle 60s und startet neu bei Absturz."""
    await asyncio.sleep(20)   # Startzeit abwarten
    while True:
        await asyncio.sleep(60)
        if not STIRLING_JAR.exists():
            continue
        if not stirling_verfuegbar():
            print("Stirling PDF: nicht erreichbar — Neustart.")
            await stirling_starten()

# ---------------------------------------------------------------------------
# Stirling PDF — API-Wrapper
# ---------------------------------------------------------------------------

async def stirling_api(
    endpunkt: str,
    dateien: list[tuple[str, bytes]],
    felder: dict | None = None,
) -> bytes | None:
    """
    Schlanker Wrapper für Stirling PDF REST-API.
    endpunkt: z.B. '/api/v1/general/compress-pdf'
    dateien:  Liste von (Dateiname, Bytes)
    felder:   Optionale Formularfelder (z.B. {"angle": "90"})
    Gibt Ergebnis-Bytes zurück oder None bei Fehler.
    """
    if not stirling_verfuegbar():
        return None
    try:
        multipart = [("fileInput", (name, daten, "application/pdf")) for name, daten in dateien]
        async with httpx.AsyncClient(timeout=120.0) as client:
            res = await client.post(
                f"{STIRLING_URL}{endpunkt}",
                files=multipart,
                data=felder or {},
            )
        return res.content if res.status_code == 200 else None
    except Exception as e:
        print(f"Stirling API Fehler ({endpunkt}): {e}")
        return None

# ---------------------------------------------------------------------------
# Stirling PDF — Telegram-Hilfsfunktionen
# ---------------------------------------------------------------------------

PDF_BEFEHLE = {
    "/pdf-compress":  ("compress",  "📎 PDF senden → ich komprimiere sie."),
    "/pdf-merge":     ("merge",     "📎 PDFs senden, dann /pdf-fertig → ich füge sie zusammen."),
    "/pdf-split":     ("split",     "📎 PDF senden. Seitenangabe z.B.: /pdf-split 1-3"),
    "/pdf-rotate":    ("rotate",    "📎 PDF senden. Winkel z.B.: /pdf-rotate 90"),
    "/pdf-topng":     ("topng",     "📎 PDF senden → ich exportiere alle Seiten als PNG-ZIP."),
    "/pdf-toexcel":   ("toexcel",   "📎 PDF senden → ich extrahiere Tabellen als CSV/Excel."),
}

PDF_ENDPUNKTE = {
    "compress": "/api/v1/general/compress-pdf",
    "merge":    "/api/v1/general/merge-pdfs",
    "split":    "/api/v1/general/split-pdf",
    "rotate":   "/api/v1/misc/rotate-pdf",
    "topng":    "/api/v1/convert/pdf/img",
    "toexcel":  "/api/v1/convert/pdf/csv",   # ⚠ nach Deployment verifizieren
}

async def handle_pdf_befehl(
    client: httpx.AsyncClient,
    tg_url: str,
    chat_id: int,
    befehl: str,
    arg: str,
):
    """Setzt PDF-Zustand für den nächsten Datei-Upload."""
    basisbefehl = befehl.split()[0].lower().split("@")[0]

    if basisbefehl == "/pdf-fertig":
        zustand = pdf_zustand.get(chat_id)
        if not zustand or zustand["op"] != "merge":
            await client.post(f"{tg_url}/sendMessage",
                json={"chat_id": chat_id, "text": "Keine aktive Merge-Operation."})
            return
        if len(zustand["dateien"]) < 2:
            await client.post(f"{tg_url}/sendMessage",
                json={"chat_id": chat_id,
                      "text": f"Bisher {len(zustand['dateien'])} Datei(en). Für Merge mindestens 2 nötig."})
            return
        await pdf_verarbeiten(client, tg_url, chat_id)
        return

    if basisbefehl == "/pdf-abbrechen":
        pdf_zustand.pop(chat_id, None)
        await client.post(f"{tg_url}/sendMessage",
            json={"chat_id": chat_id, "text": "✅ PDF-Operation abgebrochen."})
        return

    if basisbefehl not in PDF_BEFEHLE:
        return

    op, hinweis = PDF_BEFEHLE[basisbefehl]
    params: dict = {}

    # Operationsspezifische Parameter aus Argument extrahieren
    if op == "split" and arg:
        params["pages"] = arg
    elif op == "rotate":
        params["angle"] = arg if arg in ("90", "180", "270") else "90"

    pdf_zustand[chat_id] = {"op": op, "dateien": [], "params": params}
    await client.post(f"{tg_url}/sendMessage",
        json={"chat_id": chat_id, "text": hinweis, "parse_mode": "Markdown"})

async def handle_pdf_datei(
    client: httpx.AsyncClient,
    tg_url: str,
    chat_id: int,
    message: dict,
):
    """Empfängt PDF-Dokument, führt Stirling-Operation aus."""
    doc  = message.get("document", {})
    mime = doc.get("mime_type", "")
    if "pdf" not in mime.lower():
        return   # kein PDF — ignorieren

    zustand = pdf_zustand.get(chat_id)
    if not zustand:
        await client.post(f"{tg_url}/sendMessage",
            json={"chat_id": chat_id,
                  "text": "Kein aktiver PDF-Befehl. Starte z.B. mit /pdf-compress."})
        return

    # Datei herunterladen
    file_id = doc.get("file_id", "")
    r = await client.get(f"{tg_url}/getFile", params={"file_id": file_id})
    if r.status_code != 200:
        await client.post(f"{tg_url}/sendMessage",
            json={"chat_id": chat_id, "text": "❌ Download fehlgeschlagen."})
        return
    file_path = r.json().get("result", {}).get("file_path", "")
    token = tg_url.split("/bot")[1]
    dl = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
    if dl.status_code != 200:
        await client.post(f"{tg_url}/sendMessage",
            json={"chat_id": chat_id, "text": "❌ Download fehlgeschlagen."})
        return

    dateiname = Path(file_path).name
    zustand["dateien"].append((dateiname, dl.content))

    if zustand["op"] == "merge":
        n = len(zustand["dateien"])
        await client.post(f"{tg_url}/sendMessage",
            json={"chat_id": chat_id,
                  "text": f"✅ Datei {n} empfangen. Weitere senden oder /pdf-fertig."})
    else:
        await pdf_verarbeiten(client, tg_url, chat_id)

async def pdf_verarbeiten(client: httpx.AsyncClient, tg_url: str, chat_id: int):
    """Ruft Stirling API auf und sendet Ergebnis an Nutzer."""
    zustand = pdf_zustand.pop(chat_id, None)
    if not zustand:
        return

    op      = zustand["op"]
    dateien = zustand["dateien"]
    params  = zustand["params"]

    # Operationsspezifische API-Felder
    felder: dict = {}
    if op == "compress":
        felder = {"optimizeLevel": "3"}
    elif op == "split":
        felder = {"pages": params.get("pages", "1")}
    elif op == "rotate":
        felder = {"angle": params.get("angle", "90")}
    elif op == "topng":
        felder = {"imageFormat": "png", "singleOrMultiple": "multiple", "dpi": "150"}

    status = await client.post(f"{tg_url}/sendMessage",
        json={"chat_id": chat_id, "text": f"⚙️ {op} wird verarbeitet..."})
    status_id = status.json().get("result", {}).get("message_id") if status.status_code == 200 else None

    ergebnis = await stirling_api(PDF_ENDPUNKTE[op], dateien, felder)

    if ergebnis is None:
        text = "❌ Stirling PDF nicht erreichbar oder Fehler. JAR deployt und Java installiert?"
        if status_id:
            await client.post(f"{tg_url}/editMessageText",
                json={"chat_id": chat_id, "message_id": status_id, "text": text})
        else:
            await client.post(f"{tg_url}/sendMessage", json={"chat_id": chat_id, "text": text})
        return

    groesse_kb = len(ergebnis) // 1024
    suffix = ".zip" if op == "topng" else ".csv" if op == "toexcel" else ".pdf"
    ausgabename = f"{op}_ergebnis_{int(time.time())}{suffix}"

    if status_id:
        await client.post(f"{tg_url}/editMessageText",
            json={"chat_id": chat_id, "message_id": status_id,
                  "text": f"✅ {op} fertig ({groesse_kb} KB) — wird gesendet..."})

    await client.post(f"{tg_url}/sendDocument",
        data={"chat_id": str(chat_id), "caption": f"✅ {op} | {groesse_kb} KB"},
        files={"document": (ausgabename, ergebnis, "application/octet-stream")})

def get_tools_description() -> str:
    try:
        if "tools" in sys.modules:
            importlib.reload(sys.modules["tools"])
        import tools
        functions = inspect.getmembers(tools, inspect.isfunction)
        tools_desc = []
        for name, func in functions:
            if not name.startswith("_"):
                sig = inspect.signature(func)
                doc = inspect.getdoc(func) or "No description available."
                tools_desc.append(f"- tools.{name}{sig} : {doc}")
        return "\n".join(tools_desc) if tools_desc else "Keine Tools verfügbar."
    except Exception as e:
        return f"Fehler beim Laden der Tools: {e}"

def extract_code_block(text: str) -> str | None:
    match = re.search(r"```python\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else None

def run_python_code(code: str) -> str:
    work_dir = Path("C:\\AI-Tools\\AutoGen\\coding")
    work_dir.mkdir(exist_ok=True)
    file_path = work_dir / f"tmp_code_{int(time.time())}.py"
    try:
        file_path.write_text(code, encoding="utf-8")
        res = subprocess.run(
            [sys.executable, str(file_path)],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(work_dir), timeout=30
        )
        output = res.stdout
        if res.stderr:
            output += "\n" + res.stderr
        return output if output.strip() else "[Code wurde erfolgreich ohne Konsolenausgabe ausgeführt]"
    except subprocess.TimeoutExpired:
        return "Fehler: Zeitlimit von 30 Sekunden überschritten."
    except Exception as e:
        return f"Fehler bei der Ausführung: {str(e)}"

async def run_agent_loop(messages: list, model: str, chat_id: str = "global"):
    # Load memory
    facts = get_memory_for_chat(chat_id)
    memory_context = ""
    if facts:
        memory_context = "\n\nFacts you remembered about this user:\n" + "\n".join(f"- {f}" for f in facts)

    tools_desc = get_tools_description()

    system_msg = (
        "You are a helpful assistant. If you need to write files, run calculations, "
        "or process data, write Python code inside a markdown code block starting with ```python and ending with ```. "
        "The system will execute your code automatically and return the console output to you. "
        "IMPORTANT: You do NOT have internet access. Do not write Python code that attempts to "
        "fetch web pages, scrape websites, or call external web APIs. All operations must be "
        "performed completely locally.\n\n"
        "Always specify encoding='utf-8' when reading or writing files in Python to prevent errors. "
        "Specify the full code, and make sure it prints the outputs you want to see.\n\n"
        "You have a custom helper library 'tools.py' available. You can import it with 'import tools'. "
        "ALWAYS use the functions from 'tools' when reading or writing CSV/Excel files. "
        "Here are the available functions:\n"
        f"{tools_desc}"
        f"{memory_context}"
    )
    
    ollama_messages = [{"role": "system", "content": system_msg}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role in ["user", "assistant"]:
            ollama_messages.append({"role": role, "content": content})
            
    prompt_tokens = 0
    completion_tokens = 0
    
    for _ in range(3):
        response = await ollama_client.chat(model=model, messages=ollama_messages)
        prompt_tokens += response.get("prompt_eval_count", 0)
        completion_tokens += response.get("eval_count", 0)
        
        content = response["message"]["content"]
        code_block = extract_code_block(content)
        
        if not code_block:
            return content, {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}
            
        result = run_python_code(code_block)
        ollama_messages.append({"role": "assistant", "content": content})
        ollama_messages.append({"role": "user", "content": f"[System: Code-Ausgabe]:\n{result}"})
        
    return content, {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", DEFAULT_MODEL)
    openai_messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    if not stream:
        final_content, usage = await run_agent_loop(openai_messages, model, "global")
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": final_content}, "finish_reason": "stop"}],
            "usage": usage
        }
    else:
        async def event_generator():
            response_id = f"chatcmpl-{int(time.time())}"
            initial_chunk = {
                "id": response_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "delta": {"content": "Currently flying....\n\n"}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(initial_chunk)}\n\n"
            await asyncio.sleep(0.05)
            
            final_content, usage = await run_agent_loop(openai_messages, model, "global")
            
            words = final_content.split(" ")
            for i, word in enumerate(words):
                space = " " if i > 0 else ""
                chunk = {
                    "id": response_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "delta": {"content": f"{space}{word}"}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(max(0.01, min(0.05, len(word) * 0.008)))
                
            done_chunk = {
                "id": response_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": usage
            }
            yield f"data: {json.dumps(done_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream; charset=utf-8")

@app.get("/v1/models")
async def get_models():
    return {
        "object": "list",
        "data": [
            {"id": "qwen2.5:3b", "object": "model", "created": int(time.time()), "owned_by": "ollama"},
            {"id": "gemma2:9b", "object": "model", "created": int(time.time()), "owned_by": "ollama"},
            {"id": "llama3.2:3b", "object": "model", "created": int(time.time()), "owned_by": "ollama"}
        ]
    }

async def handle_telegram_command(client: httpx.AsyncClient, url: str, chat_id: int, text: str):
    parts = text.strip().split(" ", 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start":
        stirling_status = "✅ aktiv" if stirling_verfuegbar() else "⚠️ nicht erreichbar"
        welcome = (
            "🤖 *VM-Server Chatbot*\n\n"
            "*🧠 KI-Chat & Code-Ausführung*\n"
            "• `/model [qwen|gemma|llama]` — Modell wechseln\n"
            "• `/remember [Fakt]` — Fakt ins Gedächtnis speichern\n"
            "• `/forget` — Gedächtnis löschen\n"
            "• `/info` — Modell & Gedächtnis anzeigen\n"
            "• `/tools` — verfügbare Hilfsfunktionen auflisten\n\n"
            f"*📄 PDF-Verarbeitung* (Stirling PDF: {stirling_status})\n"
            "• `/pdf-compress` — PDF komprimieren\n"
            "• `/pdf-merge` — mehrere PDFs zusammenführen (dann `/pdf-fertig`)\n"
            "• `/pdf-split 1-3` — Seiten extrahieren\n"
            "• `/pdf-rotate 90` — Seiten drehen (90 / 180 / 270)\n"
            "• `/pdf-topng` — Seiten als PNG-ZIP exportieren\n"
            "• `/pdf-toexcel` — Tabellen als CSV/Excel extrahieren\n"
            "• `/pdf-abbrechen` — laufende PDF-Operation abbrechen\n\n"
            "⚠️ _Nur für nicht-DSGVO-sensitive Dokumente._\n"
            "Für vertrauliche PDFs: Web-UI intern nutzen.\n\n"
            f"Standardmodell: `{DEFAULT_MODEL}`"
        )
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": welcome, "parse_mode": "Markdown"})
        
    elif cmd == "/model":
        model_arg = arg.lower()
        if "gemma" in model_arg:
            telegram_models[chat_id] = "gemma2:9b"
            msg = "Modell gewechselt zu `gemma2:9b`."
        elif "qwen" in model_arg:
            telegram_models[chat_id] = "qwen2.5:3b"
            msg = "Modell gewechselt zu `qwen2.5:3b`."
        elif "llama" in model_arg:
            telegram_models[chat_id] = "llama3.2:3b"
            msg = "Modell gewechselt zu `llama3.2:3b`."
        else:
            msg = "Verfügbare Modelle: `qwen` (Qwen 2.5 3B), `gemma` (Gemma 2 9B), `llama` (Llama 3.2 3B). Beispiel: `/model gemma`"
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        
    elif cmd == "/remember":
        if not arg:
            msg = "Bitte geben Sie einen Fakt an, den ich mir merken soll. Beispiel: `/remember Ich bin ZEW-Mitarbeiter`"
        else:
            save_memory_for_chat(str(chat_id), arg)
            msg = f"✅ Gemerkt: *{arg}*"
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        
    elif cmd == "/forget":
        clear_memory_for_chat(str(chat_id))
        msg = "🗑️ Alle gespeicherten Fakten über Sie wurden gelöscht."
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        
    elif cmd == "/info":
        current_model = telegram_models.get(chat_id, DEFAULT_MODEL)
        facts = get_memory_for_chat(str(chat_id))
        facts_str = "\n".join(f"- {f}" for f in facts) if facts else "Keine Fakten gespeichert."
        msg = (
            f"ℹ️ **Status-Informationen:**\n\n"
            f"Aktives Modell: `{current_model}`\n\n"
            f"**Gespeichertes Gedächtnis:**\n{facts_str}"
        )
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        
    elif cmd == "/tools":
        tools_desc = get_tools_description()
        msg = f"🛠️ **Verfügbare Tools in `tools.py`:**\n\n{tools_desc}"
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

    elif cmd.startswith("/pdf-"):
        # PDF-Befehle an separaten Handler delegieren
        asyncio.create_task(handle_pdf_befehl(client, url, chat_id, text, arg))

    else:
        msg = "Unbekannter Befehl. Senden Sie `/start` für eine Liste der Befehle."
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg})

async def handle_telegram_message(client: httpx.AsyncClient, url: str, chat_id: int, text: str):
    if not is_user_allowed(chat_id):
        msg_text = (
            f"❌ Zugriff verweigert.\n\n"
            f"Ihre Chat-ID ist: `{chat_id}`\n\n"
            f"Bitte fügen Sie diese ID in der `.env`-Datei auf dem Server hinzu:\n"
            f"`TELEGRAM_ALLOWED_USERS={chat_id}`\n\n"
            f"Starten Sie danach den Dienst neu."
        )
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": msg_text, "parse_mode": "Markdown"})
        return

    # Send status message
    status_msg_response = await client.post(
        f"{url}/sendMessage", 
        json={"chat_id": chat_id, "text": "Currently flying..."}
    )
    status_msg_id = status_msg_response.json().get("result", {}).get("message_id") if status_msg_response.status_code == 200 else None
    
    # Run the ReAct agent loop
    messages = [{"role": "user", "content": text}]
    model = telegram_models.get(chat_id, DEFAULT_MODEL)
    try:
        final_content, usage = await run_agent_loop(messages, model, str(chat_id))
        response_text = f"{final_content}\n\n---\n*Tokens:* {usage.get('total_tokens', 0)} ({model})"
        
        # Try to edit status message, or send a new one if editing fails
        edit_success = False
        if status_msg_id:
            edit_res = await client.post(
                f"{url}/editMessageText",
                json={"chat_id": chat_id, "message_id": status_msg_id, "text": response_text, "parse_mode": "Markdown"}
            )
            if edit_res.status_code == 200:
                edit_success = True
                
        if not edit_success:
            await client.post(
                f"{url}/sendMessage", 
                json={"chat_id": chat_id, "text": response_text, "parse_mode": "Markdown"}
            )
    except Exception as e:
        error_text = f"Fehler bei der Verarbeitung: {str(e)}"
        await client.post(f"{url}/sendMessage", json={"chat_id": chat_id, "text": error_text})

async def telegram_bot_loop():
    # Wait for the main app startup
    await asyncio.sleep(2)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Telegram-Bot: Kein Token in TELEGRAM_BOT_TOKEN gefunden. Bot wird übersprungen.")
        return

    print("Telegram-Bot: Bot-Schleife gestartet.")
    offset = 0
    
    # We use a long timeout client for polling
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"https://api.telegram.org/bot{token}"
        while True:
            try:
                response = await client.get(
                    f"{url}/getUpdates", 
                    params={"offset": offset, "timeout": 20}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            message = update.get("message")
                            if message and "text" in message:
                                chat_id = message["chat"]["id"]
                                user_text = message["text"].strip()

                                if user_text.startswith("/"):
                                    # Process command
                                    asyncio.create_task(handle_telegram_command(client, url, chat_id, user_text))
                                else:
                                    # Process message
                                    asyncio.create_task(handle_telegram_message(client, url, chat_id, user_text))
                            elif message and "document" in message:
                                # PDF-Datei empfangen
                                chat_id = message["chat"]["id"]
                                if is_user_allowed(chat_id):
                                    asyncio.create_task(handle_pdf_datei(client, url, chat_id, message))
                else:
                    print(f"Telegram-Bot: Fehler bei getUpdates: Status {response.status_code}")
                    await asyncio.sleep(5)
            except Exception as e:
                print(f"Telegram-Bot: Verbindungsfehler: {e}")
                await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    load_dotenv()
    
    # Copy tools.py to AutoGen coding folder so executed python scripts can import it
    src_tools = Path(__file__).parent / "tools.py"
    dest_tools = Path("C:\\AI-Tools\\AutoGen\\coding\\tools.py")
    if src_tools.exists():
        try:
            dest_tools.parent.mkdir(exist_ok=True, parents=True)
            dest_tools.write_text(src_tools.read_text(encoding="utf-8"), encoding="utf-8")
            print("tools.py erfolgreich nach AutoGen\\coding kopiert.")
        except Exception as e:
            print(f"Fehler beim Kopieren von tools.py: {e}")
            
    asyncio.create_task(telegram_bot_loop())
    # Stirling PDF als Subprocess starten und überwachen
    asyncio.create_task(stirling_starten())
    asyncio.create_task(stirling_monitor_loop())
