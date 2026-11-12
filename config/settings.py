"""
JARVIS Config System - Carrega configuração de YAML + .env
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config.yaml"


# ==================== DEFAULT CONFIG ====================
DEFAULT_CONFIG = {
    # LLM Hybrid
    "llm_primary": "ollama",           # ollama | gemini
    "ollama_host": "http://localhost:11434",
    "ollama_model": "gemma3:4b",
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "gemini_model": "gemini-2.0-flash",

    # TTS Hybrid
    "tts_primary": "kokoro",           # kokoro | edge_tts
    "kokoro_voice": "pm_alex",         # pt-BR masculina (pf_dora = feminina)
    "edge_voice": "pt-BR-AntonioNeural",  # Voz grave masculina, estilo JARVIS
    "edge_rate": "-4%",
    "edge_pitch": "-8Hz",

    # Voice Gate (Speaker Recognition)
    "voice_gate_mode": "verify_sensitive",  # disabled | verify_sensitive | verify_all
    "voice_gate_user": "master",
    "voice_gate_threshold": 0.82,

    # Clap Detector
    "clap_threshold": 0.08,

    # Persona / conversa por voz
    "user_title": "senhor",            # Como o JARVIS te chama
    "conversation_window": 8.0,        # Segundos ouvindo follow-ups sem precisar dizer "jarvis"
    "voice_tools": True,               # Permite ações (abrir apps, status, casa) por voz
    "control_mode": "full",            # full = PC/celular/rede (ações perigosas pedem confirmação) | safe
    "wake_model": "tiny",              # Whisper só para detectar "Jarvis" (rápido)
    "vad_threshold": 0.5,              # Sensibilidade do detector de voz (Silero)
    "barge_in": True,                  # Dizer "Jarvis" interrompe a fala dele
    "reflexes": True,                  # Comandos comuns sem IA (abrir app, volume, status...)
    "ollama_chat_model": "",           # Modelo menor só para conversa (ex.: gemma3:4b). Vazio = mesmo modelo
    "ollama_keep_alive": "30m",        # Mantém o modelo carregado entre comandos
    "ollama_tool_mode": "prompted",    # prompted (rápido, catálogo em cache) | native
    "stt_model": "small",              # tiny | base | small | medium (pt-BR: small é bem melhor que base)

    # System
    "wake_word": "jarvis",
    "language": "pt-BR",
    "auto_start": False,
    "log_level": "INFO",
}


# ==================== CONFIG FUNCTIONS ====================
def load_config() -> dict:
    """Carrega configuração de config.yaml, mescla com defaults e .env."""
    config = DEFAULT_CONFIG.copy()

    # 1. Load from config.yaml
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
            config.update(yaml_config)
        except Exception as e:
            print(f"[Config] Erro ao ler config.yaml: {e}")

    # 2. Override with .env (environment variables take precedence)
    env_overrides = {
        "llm_primary": "JARVIS_LLM_PRIMARY",
        "ollama_host": "JARVIS_OLLAMA_HOST",
        "ollama_model": "JARVIS_OLLAMA_MODEL",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_model": "JARVIS_GEMINI_MODEL",
        "tts_primary": "JARVIS_TTS_PRIMARY",
        "kokoro_voice": "JARVIS_KOKORO_VOICE",
        "edge_voice": "JARVIS_EDGE_VOICE",
        "user_title": "JARVIS_USER_TITLE",
        "conversation_window": "JARVIS_CONVERSATION_WINDOW",
        "voice_gate_mode": "JARVIS_VOICE_GATE_MODE",
        "voice_gate_user": "JARVIS_VOICE_GATE_USER",
        "voice_gate_threshold": "JARVIS_VOICE_GATE_THRESHOLD",
        "clap_threshold": "JARVIS_CLAP_THRESHOLD",
        "wake_word": "JARVIS_WAKE_WORD",
        "language": "JARVIS_LANGUAGE",
        "auto_start": "JARVIS_AUTO_START",
        "log_level": "JARVIS_LOG_LEVEL",
    }

    for key, env_var in env_overrides.items():
        val = os.getenv(env_var)
        if val is not None:
            # Type conversion
            if key in ("voice_gate_threshold", "clap_threshold", "conversation_window", "vad_threshold"):
                config[key] = float(val)
            elif key == "auto_start":
                config[key] = val.lower() in ("true", "1", "yes")
            else:
                config[key] = val

    return config


def save_config(config: dict) -> bool:
    """Salva configuração em config.yaml."""
    try:
        # Mantém apenas chaves conhecidas
        filtered = {k: v for k, v in config.items() if k in DEFAULT_CONFIG}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(filtered, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        print(f"[Config] Erro ao salvar config.yaml: {e}")
        return False


def get_config(key: str, default=None):
    """Obtém valor de configuração específico."""
    return load_config().get(key, default)


def set_config(key: str, value) -> bool:
    """Define valor de configuração e salva."""
    config = load_config()
    if key in DEFAULT_CONFIG:
        config[key] = value
        return save_config(config)
    return False


# ==================== LEGACY SUPPORT ====================
# Para compatibilidade com código existente
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("JARVIS_MODEL", "gemini-3.5-flash")

SYSTEM_PROMPT = """
CONTEXTO TÉCNICO: você roda em um PC Windows e pode usar ferramentas para executar tarefas.

REGRAS DE FERRAMENTAS:
- Use ferramentas quando forem necessárias para cumprir o pedido; encadeie várias se preciso.
- Nunca diga que uma ação foi executada se a ferramenta não retornou sucesso.
- Para ações destrutivas ou que alterem arquivos, a aplicação pedirá confirmação.
- Trabalhe com arquivos somente dentro da pasta do projeto JARVIS.
- Não peça ao usuário para fornecer chaves, senhas ou tokens.
- Se uma ferramenta falhar, explique o erro em vez de inventar um resultado.
"""
