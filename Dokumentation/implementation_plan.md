# Implementation Plan: Schlanke Custom-Proxy-Architektur (GitHub-gestützter Workflow)

Dieses Dokument beschreibt den Plan zur Umstellung des Proxy-Dienstes auf dem Windows-Server `sts-w-0001` auf eine vereinfachte Python-Lösung ohne AutoGen/LiteLLM. Wir nutzen das GitHub-Repository **`https://github.com/steffensoldan/VM-Server`** für die Versionierung und Bereitstellung.

## User Review Required

> [!IMPORTANT]
> - **Infrastruktur-Vereinfachung:** LiteLLM und AutoGen werden deaktiviert. Der Proxy spricht direkt mit Ollama.
> - **Git-Bereitstellung:** 
>   1. Wir erstellen die Code-Dateien lokal auf Ihrem PC in `C:\Users\sts\.gemini\antigravity\playground\quantum-oort`.
>   2. Wir initialisieren Git und verbinden den Ordner mit `https://github.com/steffensoldan/VM-Server.git`.
>   3. Wir pushen den Code auf GitHub.
>   4. Auf dem Server klonen wir das Repository nach `C:\AI-Tools\VM-Server`.
>   5. Wir aktualisieren den Windows Scheduled Task `AutoGenProxy`, damit er das Skript aus dem neuen Git-Ordner ausführt.

---

## Proposed Changes

### 1. Deaktivierung von LiteLLM
Wir stoppen und deaktivieren den Dienst `LiteLLMService` auf dem Server.

```powershell
Stop-ScheduledTask -TaskName LiteLLMService
Disable-ScheduledTask -TaskName LiteLLMService
```

### 2. Lokaler Git-Setup und Code-Erstellung (auf Ihrem PC)
Wir erstellen die folgenden Dateien in Ihrem lokalen Arbeitsverzeichnis:

#### [NEW] [proxy.py](file:///C:/Users/sts/.gemini/antigravity/playground/quantum-oort/proxy.py)
Ein schlankes, robustes Python-Skript (ca. 120 Zeilen), das:
- Direkt mit der Ollama-API auf `localhost:11434` spricht (Standard-Modell: `qwen2.5:3b`).
- Python-Markdown-Codeblöcke (` ```python ... ``` `) im Antworttext sucht und per Subprozess ausführt.
- Die Ausgabenergebnisse an das Modell zurückgibt, um eine interaktive Schleife (ReAct) zu ermöglichen.
- Die Token-Nutzung dynamisch misst und an den Webchat zurückmeldet.
- Windows UTF-8-Erzwingung vornimmt.

```python
import os
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

import asyncio
import json
import time
import sys
import re
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import ollama

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ollama_client = ollama.AsyncClient(host="http://localhost:11434")
DEFAULT_MODEL = "qwen2.5:3b"

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

async def run_agent_loop(messages: list, model: str):
    system_msg = (
        "You are a helpful assistant. If you need to write files, run calculations, "
        "or process data, write Python code inside a markdown code block starting with ```python and ending with ```. "
        "The system will execute your code automatically and return the console output to you. "
        "IMPORTANT: Always specify encoding='utf-8' when reading or writing files in Python to prevent errors. "
        "Specify the full code, and make sure it prints the outputs you want to see."
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
        final_content, usage = await run_agent_loop(openai_messages, model)
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
            
            final_content, usage = await run_agent_loop(openai_messages, model)
            
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
```

#### [NEW] [requirements.txt](file:///C:/Users/sts/.gemini/antigravity/playground/quantum-oort/requirements.txt)
Definiert die minimalen Abhängigkeiten für die virtuelle Umgebung des Servers:
```text
fastapi
uvicorn
ollama
```

### 3. Git Push auf GitHub (Lokal)
Wir initialisieren das lokale Repository und pushen auf Ihr GitHub:
```powershell
git init
git remote add origin https://github.com/steffensoldan/VM-Server.git
git branch -M main
git add proxy.py requirements.txt
git commit -m "Initial commit: Custom Proxy"
git push -u origin main
```

### 4. Deployment auf dem Server `sts-w-0001` (über SSH)
Wir klonen das GitHub-Repository auf dem Server und installieren die Abhängigkeiten im bestehenden venv:
1. **GitHub Repository klonen:**
   ```powershell
   git clone https://github.com/steffensoldan/VM-Server.git C:\AI-Tools\VM-Server
   ```
2. **Abhängigkeiten im venv installieren:**
   ```powershell
   C:\AI-Tools\AutoGen\venv\Scripts\pip.exe install -r C:\AI-Tools\VM-Server\requirements.txt
   ```
3. **Scheduled Task aktualisieren:**
   Wir ändern die geplante Aufgabe `AutoGenProxy`, sodass sie das neue Skript `C:\AI-Tools\VM-Server\proxy.py` ausführt.
   - Neuer Befehl: `C:\AI-Tools\AutoGen\venv\Scripts\python.exe -m uvicorn proxy:app --host 0.0.0.0 --port 4000`
   - Startpfad (Working Directory): `C:\AI-Tools\VM-Server`
4. **Task neu starten:**
   ```powershell
   Stop-ScheduledTask -TaskName AutoGenProxy
   Start-ScheduledTask -TaskName AutoGenProxy
   ```

---

## Verification Plan

### Automated Tests
1. **Inferenz- und Codeausführungstest:** Aufruf des HTTP-Endpoints des Servers und Verifizierung, dass Qwen 2.5 3B Python-Code ausführt und Ergebnisse korrekt in UTF-8 zurückliefert.

### Manual Verification
- Test über den Webchat, um sicherzustellen, dass die Umlaut-Problematik und die Token-Zählung einwandfrei funktionieren.
