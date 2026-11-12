#!/usr/bin/env python3
"""
JARVIS CLI Unificado - Comando `jarvis` com subcomandos.
Similar ao da referência: jarvis, jarvis ask, jarvis chat, jarvis start, jarvis config, jarvis doctor
"""
import sys
import os
import argparse
import asyncio
import subprocess
import json
from pathlib import Path
from typing import Optional

# Adiciona path do projeto
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import GEMINI_API_KEY, MODEL, SYSTEM_PROMPT
from core.personality import get_personality, DEFAULT_PERSONALITY, MINIMAL_PERSONALITY, FRIENDLY_PERSONALITY


# ==================== COMANDOS ====================

def cmd_chat(args):
    """Modo chat interativo (CLI)."""
    from main import run_cli_mode
    personality = get_personality(args.personality)
    asyncio.run(run_cli_mode(personality))


def cmd_ask(args):
    """Pergunta única (não-interativo) - usa HybridLLM (Ollama + Gemini fallback) ou Brain (Gemini)."""
    from config.settings import load_config
    from core.llm_hybrid import get_hybrid_llm, LLMConfig, LLMProvider
    from core.personality import get_personality, PersonalityProcessor

    personality = get_personality(args.personality)
    personality_processor = PersonalityProcessor(personality)

    config = load_config()
    use_hybrid = config.get("llm_primary", "ollama") == "ollama"

    question = " ".join(args.question)
    print(f"Você: {question}")
    print("JARVIS: ", end="", flush=True)

    async def run():
        if use_hybrid:
            llm_config = LLMConfig(
                primary=LLMProvider(config.get("llm_primary", "ollama")),
                ollama_host=config.get("ollama_host", "http://localhost:11434"),
                ollama_model=config.get("ollama_model", "llama3.1:8b"),
                gemini_api_key=config.get("gemini_api_key", ""),
                gemini_model=config.get("gemini_model", "gemini-2.0-flash"),
                system_prompt=personality.get_system_prompt_injection(),
            )
            hybrid_llm = await get_hybrid_llm(llm_config)
            print(f"[{hybrid_llm.current_provider.value}] ", end="", flush=True)

            messages = [{"role": "system", "content": llm_config.system_prompt},
                        {"role": "user", "content": question}]

            response_buffer = []
            async for token in hybrid_llm.stream_chat(messages):
                response_buffer.append(token)
                print(token, end="", flush=True)
            print()

            full_response = "".join(response_buffer)
            processed = personality_processor.process(full_response, "general")
            # Could save to conversation history if needed
        else:
            # Legacy Brain (Gemini only)
            from core.brain import Brain
            brain = Brain(personality=personality)
            async for token in brain.think(question):
                print(token, end="", flush=True)
            print()

    asyncio.run(run())


def cmd_voice(args):
    """Modo voz contínuo (wake word: jarvis)."""
    from main import run_voice_mode
    personality = get_personality(args.personality)
    asyncio.run(run_voice_mode(personality))


def cmd_gui(args):
    """Modo GUI (PyQt6 HUD)."""
    from main import run_gui_mode
    personality = get_personality(args.personality)
    return asyncio.run(run_gui_mode(personality))


def cmd_start(args):
    """Inicia Web UI (FastAPI + Frontend) na porta 8000."""
    print("[START] Iniciando JARVIS Web UI na porta 8000...")
    print("   Acesse: http://localhost:8000")
    print("   WebSocket: ws://localhost:8000/ws")
    print("   Pressione Ctrl+C para parar")

    # Verifica se frontend existe
    frontend_dir = PROJECT_ROOT / "web" / "frontend"
    if not (frontend_dir / "index.html").exists():
        print("[AVISO]  Frontend não encontrado. Interface será básica.")
        print("   Para interface completa, o frontend já está embutido no backend.")

    # Inicia uvicorn
    os.chdir(PROJECT_ROOT)
    cmd = [
        sys.executable, "-m", "uvicorn",
        "web.backend:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")
    subprocess.run(cmd)


def cmd_config(args):
    """Gerencia configuração (get/set/list)."""
    from config.settings import GEMINI_API_KEY, MODEL, SYSTEM_PROMPT
    import config.settings as settings

    if args.action == "get":
        if args.key:
            # Tenta pegar do módulo settings
            val = getattr(settings, args.key.upper(), None)
            if val is not None:
                print(f"{args.key}: {val}")
            else:
                print(f"Chave '{args.key}' não encontrada")
        else:
            # Lista todas
            print("Configurações atuais:")
            print(f"  GEMINI_API_KEY: {'***' if GEMINI_API_KEY else 'não definido'}")
            print(f"  MODEL: {MODEL}")
            print(f"  JARVIS_MODEL: {os.getenv('JARVIS_MODEL', 'padrão')}")

    elif args.action == "set":
        if not args.key or args.value is None:
            print("Uso: jarvis config set <chave> <valor>")
            return

        # Atualiza .env
        env_path = PROJECT_ROOT / ".env"
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        key_upper = args.key.upper()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key_upper}="):
                new_lines.append(f"{key_upper}={args.value}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key_upper}={args.value}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[OK] {key_upper}={args.value} salvo em .env")
        print("   Reinicie o JARVIS para aplicar")

    elif args.action == "list":
        print("Chaves disponíveis:")
        print("  GEMINI_API_KEY  - Chave da API Gemini")
        print("  JARVIS_MODEL    - Modelo Gemini (ex: gemini-2.0-flash)")
        print("  JARVIS_OLLAMA_HOST - Host Ollama (padrão: http://localhost:11434)")
        print("  JARVIS_OLLAMA_MODEL - Modelo Ollama (padrão: gemma3:4b)")
        print("  JARVIS_TTS_PROVIDER - kokoro ou edge_tts")
        print("  JARVIS_VOICE_GATE_MODE - disabled, verify_sensitive, verify_all")


def cmd_doctor(args):
    """Diagnósticos do sistema."""
    print("[JARVIS Doctor] Diagnosticos")
    print("=" * 50)

    checks = {}

    # Python
    import sys
    py_ver = sys.version.split()[0]
    checks["python"] = f"{py_ver} {'[OK]' if sys.version_info >= (3, 10) else '[ERRO] (precisa 3.10+)'}"

    # Dependencies
    deps = [
        ("google-genai", "google.genai"),
        ("faster-whisper", "faster_whisper"),
        ("edge-tts", "edge_tts"),
        ("sounddevice", "sounddevice"),
        ("soundfile", "soundfile"),
        ("psutil", "psutil"),
        ("pyautogui", "pyautogui"),
        ("pygetwindow", "pygetwindow"),
        ("pillow", "PIL"),
        ("opencv-python", "cv2"),
        ("paho-mqtt", "paho.mqtt.client"),
        ("resemblyzer", "resemblyzer"),
        ("librosa", "librosa"),
        ("numpy", "numpy"),
        ("torch", "torch"),
        ("uvicorn", "uvicorn"),
        ("fastapi", "fastapi"),
        ("pydantic", "pydantic"),
        ("aioconsole", "aioconsole"),
    ]

    print("\n[DEPS] Dependências:")
    all_deps_ok = True
    for name, import_name in deps:
        try:
            __import__(import_name)
            print(f"  [OK] {name}")
        except ImportError:
            print(f"  [ERRO] {name} (pip install {name})")
            all_deps_ok = False

    # Ollama
    print("\n[OLLAMA] Ollama:")
    ollama_ok = False
    models = []
    try:
        import aiohttp
        async def check_ollama():
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m["name"] for m in data.get("models", [])]
                        return True, models
            return False, []
        ollama_ok, models = asyncio.run(check_ollama())
        if ollama_ok:
            print(f"  [OK] Rodando (porta 11434)")
            for m in models:
                print(f"     - {m}")
        else:
            print("  [ERRO] Não rodando (inicie: ollama serve)")
    except:
        print("  [ERRO] Erro ao verificar")

    # Gemini
    print("\n[GEMINI] Gemini API:")
    if GEMINI_API_KEY:
        print("  [OK] Configurado")
    else:
        print("  [ERRO] Não configurado (GEMINI_API_KEY no .env)")

    # Microfones
    print("\n[MIC] Microfones:")
    try:
        import sounddevice as sd
        mics = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if mics:
            for i, d in enumerate(mics):
                print(f"  [{i}] {d['name']} ({int(d['default_samplerate'])}Hz)")
        else:
            print("  [ERRO] Nenhum microfone detectado")
    except:
        print("  [ERRO] Erro ao listar")

    # Disco
    print("\n[DISK] Disco:")
    import shutil
    total, used, free = shutil.disk_usage(".")
    print(f"  Livre: {free // (1024**3)} GB / {total // (1024**3)} GB")

    # Memória
    print("\n[MEM] Memória:")
    import psutil
    mem = psutil.virtual_memory()
    print(f"  Disponível: {mem.available // (1024**3)} GB / {mem.total // (1024**3)} GB")

    # Resumo
    print("\n" + "=" * 50)
    print("[SUMMARY] Resumo:")
    issues = []
    if sys.version_info < (3, 10):
        issues.append("Python 3.10+ necessário")
    if not all_deps_ok:
        issues.append("Dependências faltando")
    if not ollama_ok and not GEMINI_API_KEY:
        issues.append("Nenhum LLM configurado (Ollama ou Gemini)")
    if not mics:
        issues.append("Nenhum microfone")

    if issues:
        print("  [AVISO]  Problemas encontrados:")
        for i in issues:
            print(f"     - {i}")
    else:
        print("  [OK] Tudo OK! JARVIS pronto para uso.")


def cmd_autostart(args):
    """Configura auto-start no Windows."""
    ps1 = PROJECT_ROOT / "automation" / "setup_autostart.ps1"
    if not ps1.exists():
        print("[ERRO] Script de auto-start não encontrado")
        return

    print("[CFG]  Configurando auto-start no Windows...")
    print("   Precisa de PowerShell como Administrador")

    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]
    if args.install:
        subprocess.run(cmd)
    else:
        print("   Execute: jarvis autostart --install")


def cmd_mqtt(args):
    """Gerencia broker MQTT (Docker)."""
    compose = PROJECT_ROOT / "automation" / "docker-compose.yml"
    if not compose.exists():
        print("[ERRO] docker-compose.yml não encontrado")
        return

    os.chdir(PROJECT_ROOT / "automation")
    if args.action == "up":
        print("[DOCKER] Iniciando Mosquitto MQTT...")
        subprocess.run(["docker-compose", "up", "-d"])
    elif args.action == "down":
        print("[STOP] Parando Mosquitto MQTT...")
        subprocess.run(["docker-compose", "down"])
    elif args.action == "logs":
        subprocess.run(["docker-compose", "logs", "-f"])
    elif args.action == "status":
        subprocess.run(["docker-compose", "ps"])


def cmd_android(args):
    """Comandos Android (ADB)."""
    if args.action == "devices":
        subprocess.run(["adb", "devices", "-l"])
    elif args.action == "connect":
        if not args.ip:
            print("Uso: jarvis android connect <IP>[:5555]")
            return
        subprocess.run(["adb", "connect", args.ip])
    elif args.action == "setup":
        print("[ANDROID] Setup Android (execute no Termux no celular):")
        print("   1. Instale Termux + Termux:API + Termux:Boot (F-Droid)")
        print("   2. termux-setup-storage")
        print("   3. bash automation/android_termux_setup.sh")
        print("   4. Edite ~/jarvis/start_jarvis.sh com IP do PC")
        print("   5. ./start_jarvis.sh")
    elif args.action == "wifi":
        print("[WIFI] Conectar via Wi-Fi:")
        print("   1. USB conectado: adb tcpip 5555")
        print("   2. adb connect IP_DO_CELULAR:5555")
        print("   3. adb devices  # deve mostrar IP:5555")


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="J.A.R.V.I.S. LEVEL 5 - Personal AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  jarvis                    # Chat interativo (CLI)
  jarvis ask "que horas são"  # Pergunta única
  jarvis voice              # Modo voz (wake word: jarvis)
  jarvis gui                # Interface gráfica (PyQt6)
  jarvis start              # Web UI (porta 8000)
  jarvis config get         # Ver config
  jarvis config set GEMINI_API_KEY sua_chave
  jarvis doctor             # Diagnósticos
  jarvis autostart --install  # Auto-start Windows
  jarvis mqtt up            # Inicia broker MQTT
  jarvis android devices    # Lista devices ADB
        """
    )

    parser.add_argument(
        '--personality', '-p',
        choices=['default', 'minimal', 'friendly'],
        default='default',
        help='Personalidade (padrão: default)'
    )

    subparsers = parser.add_subparsers(dest='command', help='Comando')

    # chat (padrão)
    p_chat = subparsers.add_parser('chat', help='Chat interativo (padrão)')
    p_chat.set_defaults(func=cmd_chat)

    # ask
    p_ask = subparsers.add_parser('ask', help='Pergunta única')
    p_ask.add_argument('question', nargs='+', help='Pergunta')
    p_ask.set_defaults(func=cmd_ask)

    # voice
    p_voice = subparsers.add_parser('voice', help='Modo voz contínuo')
    p_voice.set_defaults(func=cmd_voice)

    # gui
    p_gui = subparsers.add_parser('gui', help='Interface gráfica (PyQt6)')
    p_gui.set_defaults(func=cmd_gui)

    # start (web ui)
    p_start = subparsers.add_parser('start', help='Inicia Web UI (porta 8000)')
    p_start.add_argument('--host', default='0.0.0.0', help='Host (padrão: 0.0.0.0)')
    p_start.add_argument('--port', type=int, default=8000, help='Porta (padrão: 8000)')
    p_start.add_argument('--reload', action='store_true', help='Auto-reload (dev)')
    p_start.set_defaults(func=cmd_start)

    # config
    p_config = subparsers.add_parser('config', help='Gerencia configuração')
    p_config.add_argument('action', choices=['get', 'set', 'list'], help='Ação')
    p_config.add_argument('key', nargs='?', help='Chave')
    p_config.add_argument('value', nargs='?', help='Valor')
    p_config.set_defaults(func=cmd_config)

    # doctor
    p_doctor = subparsers.add_parser('doctor', help='Diagnósticos do sistema')
    p_doctor.set_defaults(func=cmd_doctor)

    # autostart
    p_autostart = subparsers.add_parser('autostart', help='Auto-start Windows')
    p_autostart.add_argument('--install', action='store_true', help='Instala tarefa agendada')
    p_autostart.set_defaults(func=cmd_autostart)

    # mqtt
    p_mqtt = subparsers.add_parser('mqtt', help='Broker MQTT (Docker)')
    p_mqtt.add_argument('action', choices=['up', 'down', 'logs', 'status'], help='Ação')
    p_mqtt.set_defaults(func=cmd_mqtt)

    # android
    p_android = subparsers.add_parser('android', help='Comandos Android (ADB)')
    p_android.add_argument('action', choices=['devices', 'connect', 'setup', 'wifi'], help='Ação')
    p_android.add_argument('ip', nargs='?', help='IP para connect')
    p_android.set_defaults(func=cmd_android)

    # Se nenhum comando, assume chat
    args = parser.parse_args()

    if not args.command:
        args.command = 'chat'
        args.func = cmd_chat

    if hasattr(args, 'func'):
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\n[TCHAU] Encerrado pelo usuário")
        except Exception as e:
            print(f"\n[ERRO] Erro: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()