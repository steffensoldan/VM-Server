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
        welcome = (
            "🤖 **Willkommen beim VM-Server Chatbot!**\n\n"
            "Folgende Befehle stehen zur Verfügung:\n"
            "- `/model [qwen|gemma|llama]` : Wechselt das aktive Modell für diesen Chat.\n"
            "- `/remember [Fakt]` : Speichert eine Information in Ihrem Gedächtnis.\n"
            "- `/forget` : Löscht alle gespeicherten Fakten über Sie.\n"
            "- `/info` : Zeigt das aktuelle Modell und Ihr geladenes Gedächtnis an.\n"
            "- `/tools` : Listet alle verfügbaren Programmier-Werkzeuge auf.\n\n"
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
