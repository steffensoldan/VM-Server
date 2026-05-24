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
