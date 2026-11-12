# JARVIS LEVEL 5 - upgrade script
# Execute from the root of the JARVIS project:
# powershell -ExecutionPolicy Bypass -File .\upgrade_level5.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== JARVIS LEVEL 5 ===" -ForegroundColor Cyan
Write-Host "Atualizando arquivos..." -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path "config","core","tools","memory" | Out-Null

@'
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("JARVIS_MODEL", "gemini-3.6-flash")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SYSTEM_PROMPT = """
Você é JARVIS, um assistente pessoal inteligente para Windows.
Responda em português do Brasil.

Você pode usar ferramentas para executar tarefas. Nunca diga que uma ação foi
executada se a ferramenta não retornou sucesso.

REGRAS:
- Use ferramentas quando elas forem necessárias para executar o pedido.
- Pode encadear várias ferramentas para concluir uma tarefa.
- Para ações destrutivas ou que alterem arquivos, a aplicação pedirá confirmação.
- Trabalhe com arquivos somente dentro da pasta do projeto JARVIS.
- Não peça ao usuário para fornecer chaves, senhas ou tokens.
- Seja objetivo e informe o que foi feito.
- Se uma ferramenta falhar, explique o erro em vez de inventar um resultado.
"""
'@ | Set-Content -Encoding UTF8 "config\settings.py"

@'
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent / "jarvis_memory.db"

def _connect():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return conn

def save_memory(content: str):
    conn = _connect()
    conn.execute(
        "INSERT INTO memories(content, created_at) VALUES (?, ?)",
        (content, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Memória salva."}

def recall_memory(query: str):
    conn = _connect()
    rows = conn.execute(
        "SELECT content, created_at FROM memories WHERE content LIKE ? ORDER BY id DESC LIMIT 10",
        (f"%{query}%",)
    ).fetchall()
    conn.close()
    return {
        "success": True,
        "memories": [{"content": r[0], "created_at": r[1]} for r in rows]
    }
'@ | Set-Content -Encoding UTF8 "memory\memory.py"

@'
import os
import platform
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

def _safe_path(path="."):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError("Caminho fora da pasta do projeto JARVIS.")
    return p

def open_notepad():
    subprocess.Popen(["notepad.exe"])
    return {"success": True, "message": "Bloco de Notas aberto."}

def open_calculator():
    subprocess.Popen(["calc.exe"])
    return {"success": True, "message": "Calculadora aberta."}

def open_website(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"success": False, "message": "Somente URLs HTTP/HTTPS são permitidas."}
    webbrowser.open(url)
    return {"success": True, "message": f"Site aberto: {url}"}

def get_system_info():
    return {
        "success": True,
        "computer": platform.node(),
        "system": platform.system(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cwd": str(ROOT)
    }

def list_files(path="."):
    p = _safe_path(path)
    if not p.is_dir():
        return {"success": False, "message": "Não é uma pasta."}
    items = []
    for x in sorted(p.iterdir(), key=lambda z: z.name.lower()):
        items.append({"name": x.name, "type": "folder" if x.is_dir() else "file"})
    return {"success": True, "path": str(p.relative_to(ROOT)), "items": items}

def read_file(path):
    p = _safe_path(path)
    if not p.is_file():
        return {"success": False, "message": "Arquivo não encontrado."}
    if p.stat().st_size > 2_000_000:
        return {"success": False, "message": "Arquivo grande demais para leitura direta."}
    return {
        "success": True,
        "path": str(p.relative_to(ROOT)),
        "content": p.read_text(encoding="utf-8", errors="replace")
    }

def write_file(path, content):
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"success": True, "message": f"Arquivo salvo em {p.relative_to(ROOT)}."}

def delete_file(path):
    p = _safe_path(path)
    if not p.exists() or not p.is_file():
        return {"success": False, "message": "Arquivo não encontrado."}
    p.unlink()
    return {"success": True, "message": f"Arquivo apagado: {p.relative_to(ROOT)}"}

def get_time():
    return {"success": True, "datetime": datetime.now().isoformat(timespec="seconds")}

def open_app(app):
    allowed = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe"
    }
    exe = allowed.get(app.lower())
    if not exe:
        return {"success": False, "message": "Aplicativo não autorizado."}
    subprocess.Popen([exe])
    return {"success": True, "message": f"{app} aberto."}
'@ | Set-Content -Encoding UTF8 "tools\system.py"

@'
from tools.system import (
    open_notepad, open_calculator, open_website, get_system_info,
    list_files, read_file, write_file, delete_file, get_time, open_app
)
from memory.memory import save_memory, recall_memory

FUNCTIONS = {
    "open_notepad": open_notepad,
    "open_calculator": open_calculator,
    "open_website": open_website,
    "get_system_info": get_system_info,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "delete_file": delete_file,
    "get_time": get_time,
    "open_app": open_app,
    "save_memory": save_memory,
    "recall_memory": recall_memory,
}

DANGEROUS = {"delete_file", "write_file"}

class Router:
    def execute(self, function_name, arguments=None):
        arguments = arguments or {}
        fn = FUNCTIONS.get(function_name)

        if not fn:
            return {"success": False, "message": f"Ferramenta desconhecida: {function_name}"}

        if function_name in DANGEROUS:
            print(f"\n[CONFIRMAÇÃO] JARVIS quer executar: {function_name}")
            print(f"Argumentos: {arguments}")
            answer = input("Confirmar? [s/N]: ").strip().lower()
            if answer not in ("s", "sim", "y", "yes"):
                return {"success": False, "message": "Ação cancelada pelo usuário."}

        try:
            return fn(**arguments)
        except Exception as e:
            return {"success": False, "message": f"Erro: {type(e).__name__}: {e}"}
'@ | Set-Content -Encoding UTF8 "core\router.py"

@'
import json
from google import genai
from config.settings import GEMINI_API_KEY, MODEL, SYSTEM_PROMPT
from core.router import Router

class Brain:
    def __init__(self):
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY não encontrada no .env")

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.router = Router()
        self.previous_interaction_id = None

        self.tools = [
            {"type": "function", "name": "open_notepad",
             "description": "Abre o Bloco de Notas.",
             "parameters": {"type": "object", "properties": {}}},

            {"type": "function", "name": "open_calculator",
             "description": "Abre a Calculadora.",
             "parameters": {"type": "object", "properties": {}}},

            {"type": "function", "name": "open_website",
             "description": "Abre um site no navegador.",
             "parameters": {"type": "object", "properties": {
                 "url": {"type": "string"}
             }, "required": ["url"]}},

            {"type": "function", "name": "get_system_info",
             "description": "Obtém informações do computador.",
             "parameters": {"type": "object", "properties": {}}},

            {"type": "function", "name": "list_files",
             "description": "Lista arquivos de uma pasta dentro do projeto JARVIS.",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string"}
             }}},

            {"type": "function", "name": "read_file",
             "description": "Lê um arquivo de texto dentro do projeto JARVIS.",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string"}
             }, "required": ["path"]}},

            {"type": "function", "name": "write_file",
             "description": "Cria ou substitui um arquivo de texto. Requer confirmação.",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string"},
                 "content": {"type": "string"}
             }, "required": ["path", "content"]}},

            {"type": "function", "name": "delete_file",
             "description": "Apaga um arquivo. Requer confirmação.",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string"}
             }, "required": ["path"]}},

            {"type": "function", "name": "get_time",
             "description": "Retorna a data e hora locais.",
             "parameters": {"type": "object", "properties": {}}},

            {"type": "function", "name": "open_app",
             "description": "Abre um aplicativo permitido: notepad, calculator ou paint.",
             "parameters": {"type": "object", "properties": {
                 "app": {"type": "string", "enum": ["notepad", "calculator", "paint"]}
             }, "required": ["app"]}},

            {"type": "function", "name": "save_memory",
             "description": "Salva uma informação que o usuário pediu para lembrar.",
             "parameters": {"type": "object", "properties": {
                 "content": {"type": "string"}
             }, "required": ["content"]}},

            {"type": "function", "name": "recall_memory",
             "description": "Procura memórias salvas relacionadas a uma consulta.",
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string"}
             }, "required": ["query"]}},

            {"type": "google_search"},
        ]

    def think(self, user_message):
        kwargs = {
            "model": MODEL,
            "input": user_message,
            "tools": self.tools,
        }

        if self.previous_interaction_id:
            kwargs["previous_interaction_id"] = self.previous_interaction_id

        interaction = self.client.interactions.create(**kwargs)

        while True:
            calls = [s for s in interaction.steps if s.type == "function_call"]

            if not calls:
                self.previous_interaction_id = interaction.id
                return interaction.output_text or "Concluído."

            results = []

            for call in calls:
                print(f"\n[JARVIS] Ferramenta: {call.name}")
                result = self.router.execute(call.name, call.arguments or {})

                results.append({
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False)
                        }
                    ],
                })

            interaction = self.client.interactions.create(
                model=MODEL,
                previous_interaction_id=interaction.id,
                input=results,
                tools=self.tools,
            )
'@ | Set-Content -Encoding UTF8 "core\brain.py"

@'
from core.brain import Brain

def main():
    print("=" * 60)
    print("                 J.A.R.V.I.S. LEVEL 5")
    print("             Personal AI Agent - Windows")
    print("=" * 60)
    print("JARVIS online. Digite 'sair' para encerrar.")
    print()

    brain = Brain()

    while True:
        try:
            user = input("Você: ").strip()

            if not user:
                continue

            if user.lower() in {"sair", "exit", "quit"}:
                print("JARVIS: Até logo.")
                break

            print(f"\nJARVIS: {brain.think(user)}\n")

        except KeyboardInterrupt:
            print("\nJARVIS: Encerrando.")
            break

        except Exception as e:
            print(f"\n[JARVIS ERROR] {type(e).__name__}: {e}\n")

if __name__ == "__main__":
    main()
'@ | Set-Content -Encoding UTF8 "main.py"

@'
google-genai
python-dotenv
'@ | Set-Content -Encoding UTF8 "requirements.txt"

@'
.env
__pycache__/
*.pyc
.venv/
memory/*.db
'@ | Set-Content -Encoding UTF8 ".gitignore"

Write-Host "Instalando/atualizando dependências..." -ForegroundColor Yellow
python -m pip install -U google-genai python-dotenv

Write-Host "Validando Python..." -ForegroundColor Yellow
python -m py_compile config\settings.py
python -m py_compile memory\memory.py
python -m py_compile tools\system.py
python -m py_compile core\router.py
python -m py_compile core\brain.py
python -m py_compile main.py

Write-Host ""
Write-Host "JARVIS LEVEL 5 instalado com sucesso." -ForegroundColor Green
Write-Host "Seu .env NÃO foi alterado." -ForegroundColor Green
Write-Host ""
Write-Host "Agora execute:" -ForegroundColor Cyan
Write-Host "python main.py" -ForegroundColor White
