"""
JarvisAgent - o "cérebro de campo" do J.A.R.V.I.S.

Responde com a persona do filme E executa ações de verdade:
  - Ollama local (ex.: llama3.1:8b) com function calling, ou
  - Gemini (Brain) com function calling,
com fallback automático entre os dois.

No modo voz usa um conjunto curado de ferramentas seguras (VOICE_TOOLSET):
mandar as ~190 ferramentas confunde modelos pequenos e deixa tudo lento.
Ferramentas perigosas (desligar PC, apagar arquivo, PowerShell...) nunca são
executadas por voz sem confirmação.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime
from typing import AsyncGenerator, Awaitable, Callable, Optional

import aiohttp

from config.settings import SYSTEM_PROMPT, load_config
from core.personality import Personality, DEFAULT_PERSONALITY
from core.plugin_system import auto_discover_tools, get_gemini_functions, get_tool

# Callback de confirmação: recebe (nome_da_ferramenta, argumentos) -> True se autorizado
ConfirmFn = Callable[[str, dict], Awaitable[bool]]
from core.router import Router

# Ferramentas úteis e seguras para comandos de voz no estilo JARVIS
VOICE_TOOLSET = [
    # Aplicativos / web
    "open_app", "open_website", "open_calculator", "open_notepad",
    # Janelas / teclado
    "list_windows", "activate_window", "window_control", "hotkey", "press_key", "type_text",
    # Sistema / diagnóstico
    "get_time", "get_system_info", "hardware_info", "network_info", "list_processes",
    # Tela
    "screenshot", "screen_ocr",
    # Arquivos (somente leitura)
    "search_files", "list_files", "read_file",
    # Casa inteligente (Home Assistant)
    "hass_get_states", "hass_get_state", "hass_turn_on", "hass_turn_off", "hass_toggle",
    "hass_set_light", "hass_set_climate", "hass_media_control",
]

# Modo "full": controle total do PC, celular e rede. Ações perigosas pedem
# confirmação por voz antes de executar.
FULL_TOOLSET = VOICE_TOOLSET + [
    # PC - controle total
    "run_powershell", "kill_process", "power_control", "manage_service",
    "write_file", "delete_file", "registry_edit", "unlock_pc",
    "move_mouse", "click", "drag", "get_mouse_position", "screen_find_text",
    # Celular Android (ADB via USB ou Wi-Fi)
    "adb_list_devices", "android_devices", "android_connect_wifi", "adb_get_battery",
    "android_system_info", "android_open_app", "android_close_app", "adb_start_app",
    "adb_input_text", "adb_input_tap", "adb_input_swipe", "adb_input_key", "adb_screencap",
    "android_notifications", "android_send_notification", "android_settings",
    "android_communication", "android_shell",
    # Rede Wi-Fi / outros aparelhos
    "scan_devices_once", "list_devices", "network_test", "network_ssh_exec",
    "device_network_discover", "device_network_list", "device_network_command",
    "network_http_request", "network_mqtt_publish",
]

# Grupos de ferramentas por assunto. Modelos locais pequenos (8B) erram muito com
# dezenas de ferramentas; enviamos só os grupos relevantes ao pedido.
TOOL_GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # nome: (palavras-gatilho (sem acento), ferramentas)
    "apps": (("abr", "inici", "lanc", "navegador", "site", "youtube", "google", "spotify", "chrome",
              "calculadora", "bloco de notas", "programa", "aplicativo", "app "),
             ("open_app", "open_website", "open_calculator", "open_notepad")),
    "windows": (("janela", "minimiz", "maximiz", "fech", "digit", "escrev", "tecla", "atalho", "clique",
                 "clica", "mouse", "cursor", "arrast", "foco", "alterne"),
                ("list_windows", "activate_window", "window_control", "hotkey", "press_key", "type_text",
                 "move_mouse", "click", "drag", "get_mouse_position")),
    "system": (("memoria", "ram", "cpu", "processador", "disco", "bateria", "processo", "sistema",
                "servico", "rede", "internet", " ip", "temperatura do pc", "hardware", "desempenho",
                "lento", "travando", "mata", "matar", "encerr", "uso"),
               ("get_system_info", "hardware_info", "list_processes", "kill_process", "network_info",
                "manage_service", "get_time")),
    "power": (("deslig", "reinic", "hibern", "suspend", "bloque", "desbloque", "dormir o pc", "acord"),
              ("power_control", "unlock_pc")),
    "shell": (("powershell", "comando", "terminal", "cmd", "registro", "script", "instal", "winget",
               "execute", "rode", "roda"),
              ("run_powershell", "registry_edit")),
    "files": (("arquivo", "pasta", "documento", "salv", "apag", "delet", "leia", "ler o", "procur",
               "encontr", "diretorio"),
              ("search_files", "list_files", "read_file", "write_file", "delete_file")),
    "screen": (("tela", "print", "captur", "screenshot", "monitor", "o que esta escrito"),
               ("screenshot", "screen_ocr", "screen_find_text")),
    "phone": (("celular", "telefone", "android", "smartphone", "notificac", "mensagem", "sms",
               "ligue para", "ligar para", "ligacao", "adb", "whatsapp"),
              ("adb_list_devices", "android_devices", "android_connect_wifi", "adb_get_battery",
               "android_system_info", "android_open_app", "android_close_app", "adb_start_app",
               "adb_input_text", "adb_input_tap", "adb_input_swipe", "adb_input_key", "adb_screencap",
               "android_notifications", "android_send_notification", "android_settings",
               "android_communication", "android_shell")),
    "network": (("dispositivo", "aparelho", "wifi", "wi-fi", "ssh", "servidor", "raspberry", "ping",
                 "conectad", "na rede", "da rede", "scan", "varr", "mqtt", "roteador"),
                ("scan_devices_once", "list_devices", "network_test", "network_ssh_exec",
                 "device_network_discover", "device_network_list", "device_network_command",
                 "network_http_request", "network_mqtt_publish", "network_info")),
    "home": (("luz", "luzes", "lampada", "ar condicionado", "ar-condicionado", "climatiz", "tomada",
              "fechadura", "portao", "cortina", "persiana", "musica", "volume", "casa", "tv", "televis"),
             ("hass_get_states", "hass_get_state", "hass_turn_on", "hass_turn_off", "hass_toggle",
              "hass_set_light", "hass_set_climate", "hass_media_control")),
}


def _strip_accents(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def select_tool_names(text: str) -> set[str]:
    """Ferramentas relevantes para o pedido (vazio = conversa, sem ferramentas)."""
    t = " " + _strip_accents(text) + " "
    names: set[str] = set()
    for keywords, tools in TOOL_GROUPS.values():
        if any(k in t for k in keywords):
            names.update(tools)
    return names


# Além das marcadas como perigosas no plugin system, estas também exigem confirmação
EXTRA_CONFIRM = {
    "network_ssh_exec", "device_network_command", "adb_input_text", "adb_input_tap",
    "adb_input_swipe", "unlock_pc", "network_http_request", "network_mqtt_publish",
}

MAX_TOOL_ROUNDS = 5
HISTORY_LIMIT = 16


# ==================== Relatório de status (estilo filme) ====================

def _num_pt(n: float) -> str:
    return str(int(round(n)))


def system_report(title: str = "senhor") -> str:
    """Relatório curto e falável do estado do PC."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory().percent
        parts = [f"Processador a {_num_pt(cpu)} por cento", f"memória a {_num_pt(mem)}"]
        bat = psutil.sensors_battery()
        if bat is not None:
            if bat.power_plugged:
                parts.append(f"bateria em {_num_pt(bat.percent)} por cento, na tomada")
            else:
                parts.append(f"bateria em {_num_pt(bat.percent)} por cento")
        alert = ""
        if mem >= 90 or cpu >= 90:
            alert = f" Recomendo atenção, {title}: os recursos estão no limite."
        elif bat is not None and not bat.power_plugged and bat.percent <= 20:
            alert = f" Sugiro conectar o carregador, {title}."
        status = "Todos os sistemas operacionais" if not alert else "Sistemas operacionais"
        return f"{status}. " + ", ".join(parts) + "." + alert
    except Exception:
        return "Todos os sistemas operacionais."


def time_greeting(title: str = "senhor") -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return f"Bom dia, {title}."
    if 12 <= hour < 18:
        return f"Boa tarde, {title}."
    if hour >= 23 or hour < 5:
        return f"Boa noite, {title}. Trabalhando até tarde outra vez, vejo."
    return f"Boa noite, {title}."


# ==================== Ollama com ferramentas ====================

class OllamaToolAgent:
    """Chat com Ollama /api/chat + function calling (modelos com capability 'tools')."""

    def __init__(self, host: str, model: str, tools: list[dict], router: Router, dangerous: set[str]):
        self.confirm: Optional[ConfirmFn] = None
        self._last_selected: set[str] = set()
        self.host = host.rstrip("/")
        self.model = model
        self.router = router
        self.dangerous = dangerous
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _clean_schema(t.get("parameters") or {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]
        self.history: list[dict] = []

    async def is_available(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(f"{self.host}/api/tags") as r:
                    if r.status != 200:
                        return False
                    data = await r.json()
                    names = {m.get("name") for m in data.get("models", [])}
                    return self.model in names or f"{self.model}:latest" in names
        except Exception:
            return False

    async def _chat(self, session: aiohttp.ClientSession, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.6, "top_p": 0.9},
        }
        if tools:
            payload["tools"] = tools
        async with session.post(f"{self.host}/api/chat", json=payload) as r:
            if r.status != 200:
                raise RuntimeError(f"Ollama {r.status}: {await r.text()}")
            return (await r.json()).get("message", {})

    async def respond(self, text: str, system_prompt: str, use_tools: bool) -> str:
        # Só as ferramentas relevantes a este pedido (+ as do pedido anterior, p/ follow-ups)
        selected = select_tool_names(text) if use_tools else set()
        active = selected | self._last_selected
        self._last_selected = selected
        tools = [t for t in self.tools if t["function"]["name"] in active]
        if tools:
            print(f"[JARVIS] Ferramentas oferecidas: {len(tools)}")

        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": system_prompt}] + self.history[-HISTORY_LIMIT:]

        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            cancelled = executed = False
            for _ in range(MAX_TOOL_ROUNDS + 1):
                msg = await self._chat(session, messages, tools)
                calls = msg.get("tool_calls") or []
                if not calls:
                    answer = (msg.get("content") or "").strip()
                    if cancelled and not executed:
                        # Modelos pequenos às vezes "inventam" o resultado de ações canceladas
                        answer = "Como desejar. A ação não foi executada."
                    self.history.append({"role": "assistant", "content": answer})
                    self.history = self.history[-HISTORY_LIMIT:]
                    return answer

                messages.append(msg)
                for call in calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result = await execute_tool(self.router, name, args, self.dangerous, self.confirm)
                    if result.get("cancelled"):
                        cancelled = True
                    elif result.get("success"):
                        executed = True
                    messages.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
            # Excedeu rodadas: pede resposta final sem ferramentas
            msg = await self._chat(session, messages, [])
            answer = (msg.get("content") or "").strip()
            self.history.append({"role": "assistant", "content": answer})
            return answer

    def reset(self) -> None:
        self.history.clear()
        self._last_selected = set()


def _clean_schema(schema: dict) -> dict:
    """Remove 'default: None' (Ollama/llama se confundem) e garante formato válido."""
    schema = json.loads(json.dumps(schema))
    for prop in (schema.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("default", 0) is None:
            prop.pop("default")
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _coerce_args(fn, args: dict) -> dict:
    """Converte argumentos para os tipos declarados na ferramenta.

    Modelos pequenos mandam "false"/"10" como texto; sem isso, "false" (string
    não vazia) viraria True - ex.: PowerShell rodando como administrador.
    """
    import inspect
    import typing
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = getattr(fn, "__annotations__", {})
    params = inspect.signature(fn).parameters
    out = {}
    for key, value in (args or {}).items():
        if key not in params:
            continue  # descarta argumentos inventados pelo modelo
        hint = hints.get(key)
        if isinstance(value, str) and hint in (bool, Optional[bool]):
            value = value.strip().lower() in ("true", "1", "sim", "yes")
        elif isinstance(value, str) and hint in (int, Optional[int]):
            try:
                value = int(float(value))
            except ValueError:
                pass
        elif isinstance(value, str) and hint in (float, Optional[float]):
            try:
                value = float(value)
            except ValueError:
                pass
        out[key] = value
    return out


CANCELLED_MSG = "CANCELADO pelo usuário. A ação NÃO foi executada e não há resultado."


async def execute_tool(
    router: Router, name: str, args: dict, needs_confirm: set[str], confirm: Optional[ConfirmFn]
) -> dict:
    """Executa uma ferramenta; as sensíveis só rodam após confirmação explícita."""
    print(f"[JARVIS] Ferramenta: {name}({args})")
    spec = get_tool(name)
    if spec is None:
        return {"success": False, "message": f"Ferramenta desconhecida: {name}"}

    loop = asyncio.get_running_loop()
    args = _coerce_args(spec.function, args)
    try:
        if name in needs_confirm or spec.is_dangerous:
            if confirm is None or not await confirm(name, args):
                return {"success": False, "cancelled": True, "message": CANCELLED_MSG}
        # Chama a função direto: a confirmação já foi feita acima (o Router pediria
        # input() no terminal) e ferramentas async precisam de await.
        if inspect.iscoroutinefunction(spec.function):
            result = await spec.function(**args)
        else:
            result = await loop.run_in_executor(None, lambda: spec.function(**args))
    except Exception as e:
        result = {"success": False, "message": f"{type(e).__name__}: {e}"}

    if not isinstance(result, dict):
        result = {"success": True, "result": result}
    status = "OK" if result.get("success") else "FALHOU"
    print(f"[JARVIS]   -> {status}: {str(result.get('message', ''))[:120]}")
    return result


# ==================== Agente principal ====================

class JarvisAgent:
    """Escolhe o motor (Ollama/Gemini), injeta a persona e executa ferramentas."""

    def __init__(self, personality: Personality = DEFAULT_PERSONALITY, config: Optional[dict] = None):
        self.personality = personality
        self.config = config or load_config()
        self.router = Router()
        auto_discover_tools()
        all_tools = get_gemini_functions()
        self.dangerous = self.router.get_dangerous_tools()
        self.needs_confirm = self.dangerous | EXTRA_CONFIRM
        mode = str(self.config.get("control_mode", "full")).lower()
        wanted = FULL_TOOLSET if mode == "full" else VOICE_TOOLSET
        self.voice_tools = [t for t in all_tools if t["name"] in wanted]
        if mode != "full":
            self.voice_tools = [t for t in self.voice_tools if t["name"] not in self.needs_confirm]
        self.confirm: Optional[ConfirmFn] = None

        self.ollama = OllamaToolAgent(
            host=self.config.get("ollama_host", "http://localhost:11434"),
            model=self.config.get("ollama_model", "llama3.1:8b"),
            tools=self.voice_tools,
            router=self.router,
            dangerous=self.needs_confirm,
        )
        self.brain = None
        try:
            from core.brain import Brain
            self.brain = Brain(personality=personality, model=self.config.get("gemini_model") or None)
        except Exception as e:
            print(f"[JARVIS] Gemini indisponível: {e}")

        self.engine: Optional[str] = None

    async def initialize(self) -> str:
        ollama_ok = await self.ollama.is_available()
        prefer = self.config.get("llm_primary", "ollama")
        if prefer == "ollama" and ollama_ok:
            self.engine = "ollama"
        elif self.brain is not None:
            self.engine = "gemini"
        elif ollama_ok:
            self.engine = "ollama"
        else:
            raise RuntimeError(
                "Nenhum motor de IA disponível. Inicie o Ollama ou configure GEMINI_API_KEY no .env."
            )
        print(f"[JARVIS] Motor: {self.engine} | ferramentas de voz: {len(self.voice_tools)}")
        return self.engine

    def system_prompt(self, spoken: bool) -> str:
        now = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
        return (
            self.personality.get_system_prompt_injection(spoken=spoken)
            + f"\n\nDATA/HORA ATUAL: {now}\n\n"
            + SYSTEM_PROMPT.strip()
        )

    async def respond(self, text: str, spoken: bool = True) -> AsyncGenerator[str, None]:
        """Gera a resposta (em pedaços). Faz fallback entre motores em caso de erro."""
        use_tools = bool(self.config.get("voice_tools", True))
        order = [self.engine] + [e for e in ("ollama", "gemini") if e != self.engine]
        last_error: Optional[Exception] = None

        for engine in order:
            if engine == "gemini" and self.brain is None:
                continue
            try:
                if engine == "ollama":
                    self.ollama.confirm = self.confirm
                    answer = await self.ollama.respond(text, self.system_prompt(spoken), use_tools)
                    yield answer
                else:
                    async for token in self.brain.think(
                        text,
                        use_tools=use_tools,
                        tool_names=[t["name"] for t in self.voice_tools],
                        spoken=spoken,
                        tool_executor=self._execute,
                    ):
                        yield token
                if engine != self.engine:
                    print(f"[JARVIS] Motor alternado para {engine}")
                    self.engine = engine
                return
            except Exception as e:
                last_error = e
                print(f"[JARVIS] Motor {engine} falhou: {e}")
        raise RuntimeError(f"Todos os motores falharam: {last_error}")

    async def _execute(self, name: str, args: dict) -> dict:
        return await execute_tool(self.router, name, args, self.needs_confirm, self.confirm)

    def reset(self) -> None:
        self.ollama.reset()
        if self.brain:
            self.brain.reset()
