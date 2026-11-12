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
import re
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
    # Aplicativos / web / mídia
    "launch_app", "open_site", "close_app", "media_control", "show_desktop",
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
    "lan_devices", "scan_devices_once", "list_devices", "network_test", "network_ssh_exec",
    "device_network_discover", "device_network_list", "device_network_command",
    "network_http_request", "network_mqtt_publish",
]

# Grupos de ferramentas por assunto. Modelos locais pequenos (8B) erram muito com
# dezenas de ferramentas; enviamos só os grupos relevantes ao pedido.
TOOL_GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # nome: (palavras-gatilho (sem acento), ferramentas)
    "apps": (("abra", "abre ", "abrir", "inici", "lanc", "navegador", "site", "youtube", "google", "pesquis", "busque",
              "programa", "aplicativo", " app"),
             ("launch_app", "open_site", "close_app")),
    "media": (("musica", "volume", "som ", "pausa", "pause", "faixa", "toca ", "tocar", "video", "mudo"),
              ("media_control",)),
    "windows": (("janela", "minimiz", "maximiz", "fech", "foco", "alterne", "troque para", "va para",
                 "area de trabalho"),
                ("list_windows", "activate_window", "window_control", "close_app", "show_desktop")),
    "input": (("digit", "escrev", "tecla", "atalho", "clique", "clica", "mouse", "cursor", "arrast",
               "aperte", "pressione", "ctrl", "copie", "cole"),
              ("hotkey", "press_key", "type_text", "click", "move_mouse", "drag", "get_mouse_position")),
    "system": (("memoria", "ram", "cpu", "processador", "disco", "bateria", "processo", "sistema",
                "servico", "internet", " ip", "hardware", "desempenho", "lento", "travando", "mata",
                "matar", "encerr", "uso"),
               ("get_system_info", "hardware_info", "list_processes", "kill_process", "network_info",
                "manage_service")),
    "power": (("deslig", "reinic", "hibern", "suspend", "bloque", "desbloque", "dormir o pc", "acord"),
              ("power_control", "unlock_pc")),
    "shell": (("powershell", "comando", "terminal", "cmd", "registro", "script", "instal", "winget",
               "execute", "rode", "roda"),
              ("run_powershell", "registry_edit")),
    "files": (("arquivo", "pasta", "documento", "salv", "apag", "delet", "leia", "ler o", "procur",
               "encontr", "diretorio", "planilha"),
              ("search_files", "list_files", "read_file", "write_file", "delete_file")),
    "screen": (("tela", "print", "captur", "screenshot", "monitor", "o que esta escrito"),
               ("screenshot", "screen_ocr", "screen_find_text")),
    "phone": (("celular", "telefone", "android", "smartphone", "notificac", "mensagem", "sms",
               "ligue para", "ligar para", "ligacao", "adb", "whatsapp"),
              ("adb_list_devices", "android_connect_wifi", "adb_get_battery", "android_open_app",
               "adb_input_text", "android_notifications", "android_send_notification",
               "android_communication", "android_shell")),
    "phone_screen": (("tela do celular", "print do celular", "toque na", "toca na", "desliz", "arraste no celular",
                      "configurac", "wi-fi do celular", "bluetooth do celular"),
                     ("adb_input_tap", "adb_input_swipe", "adb_input_key", "adb_screencap",
                      "android_settings", "android_system_info", "android_close_app")),
    "network": (("dispositivo", "aparelho", "wifi", "wi-fi", "ssh", "servidor", "raspberry", "ping",
                 "conectad", "na rede", "da rede", "scan", "varr", "mqtt", "roteador"),
                ("lan_devices", "list_devices", "network_test", "network_ssh_exec",
                 "device_network_discover", "device_network_list", "device_network_command",
                 "network_http_request", "network_mqtt_publish", "network_info")),
    "home": (("luz", "luzes", "lampada", "ar condicionado", "ar-condicionado", "climatiz", "tomada",
              "fechadura", "portao", "cortina", "persiana", "casa", "tv", "televis"),
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
DEBUG = bool(__import__('os').environ.get('JARVIS_DEBUG'))
WEEKDAYS_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
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

    def __init__(self, host: str, model: str, tools: list[dict], router: Router, dangerous: set[str],
                 chat_model: str = "", keep_alive: str = "30m", tool_mode: str = "prompted"):
        self.chat_model = chat_model or model
        self.keep_alive = keep_alive
        self.tool_mode = tool_mode
        self._catalog_cache: Optional[str] = None
        self.max_tokens: Optional[int] = None   # definido por pedido (voz = curto)
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
                    "description": _short(t.get("description", "")),
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

    def _payload(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        options = {"temperature": 0.6, "top_p": 0.9, "num_ctx": 8192}
        if self.max_tokens:
            options["num_predict"] = self.max_tokens
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.keep_alive,   # mantém o modelo na memória entre comandos
            "options": options,
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def _stream_chat(self, session: aiohttp.ClientSession, model: str, messages: list[dict],
                           tools: list[dict], out_calls: list) -> AsyncGenerator[str, None]:
        """Streaming do texto; chamadas de ferramenta são acumuladas em out_calls."""
        async with session.post(f"{self.host}/api/chat", json=self._payload(model, messages, tools)) as r:
            if r.status != 200:
                raise RuntimeError(f"Ollama {r.status}: {await r.text()}")
            async for line in r.content:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise RuntimeError(f"Ollama: {data['error']}")
                msg = data.get("message") or {}
                if msg.get("tool_calls"):
                    out_calls.extend(msg["tool_calls"])
                if msg.get("content"):
                    yield msg["content"]
                if data.get("done"):
                    if DEBUG:
                        print(f"[Ollama] {model}: prompt={data.get('prompt_eval_count')} tok "
                              f"em {data.get('prompt_eval_duration', 0) / 1e9:.1f}s | "
                              f"geração={data.get('eval_count')} tok em {data.get('eval_duration', 0) / 1e9:.1f}s")
                    break

    async def warmup(self, system_prompt: str) -> None:
        """Carrega o modelo e pré-processa o prompt do sistema (cache de prefixo)."""
        try:
            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                models = {self.model, self.chat_model}
                for model in models:
                    sysp = self.full_system(system_prompt) if model == self.model else system_prompt
                    payload = self._payload(model, [{"role": "system", "content": sysp},
                                                    {"role": "user", "content": "Olá."}], [])
                    payload["stream"] = False
                    payload["options"]["num_predict"] = 1
                    async with session.post(f"{self.host}/api/chat", json=payload) as r:
                        await r.read()
            print(f"[JARVIS] Modelo local aquecido: {', '.join(sorted(models))}")
        except Exception as e:
            print(f"[JARVIS] Aquecimento do Ollama falhou: {e}")

    async def respond_stream(self, text: str, system_prompt: str, use_tools: bool) -> AsyncGenerator[str, None]:
        """Resposta em streaming, executando ferramentas quando o modelo pedir."""
        # Só as ferramentas relevantes a este pedido (+ as do pedido anterior, p/ follow-ups)
        selected = select_tool_names(text) if use_tools else set()
        active = selected | self._last_selected
        self._last_selected = selected
        tools = [t for t in self.tools if t["function"]["name"] in active]
        # Conversa sem ferramentas pode usar um modelo menor e mais rápido
        model = self.model if tools else self.chat_model
        if tools:
            print(f"[JARVIS] Ferramentas oferecidas: {len(tools)}")

        # A hora vai na mensagem (não no prompt do sistema) para o prefixo ficar
        # idêntico entre pedidos e o Ollama reaproveitar o cache.
        now = datetime.now()
        stamped = f"{text}\n(agora: {now:%H:%M}, {WEEKDAYS_SHORT[now.weekday()]} {now:%d/%m/%Y})"
        self.history.append({"role": "user", "content": stamped})
        messages = [{"role": "system", "content": system_prompt}] + self.history[-HISTORY_LIMIT:]

        answer_parts: list[str] = []
        timeout = aiohttp.ClientTimeout(total=300, sock_read=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for _ in range(MAX_TOOL_ROUNDS + 1):
                    calls: list = []
                    async for token in self._stream_chat(session, model, messages, tools, calls):
                        answer_parts.append(token)
                        yield token
                    if not calls:
                        return

                    messages.append({"role": "assistant", "content": "", "tool_calls": calls})
                    cancelled = executed = False
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
                            "content": compact_result(result),
                        })
                    if cancelled and not executed:
                        # Não deixa o modelo "inventar" o resultado de uma ação cancelada
                        msg = "Como desejar. A ação não foi executada."
                        answer_parts.append(msg)
                        yield msg
                        return
                # Excedeu as rodadas: resposta final sem ferramentas
                async for token in self._stream_chat(session, self.model, messages, [], []):
                    answer_parts.append(token)
                    yield token
        finally:
            self.history.append({"role": "assistant", "content": "".join(answer_parts).strip() or "(interrompido)"})
            self.history = self.history[-HISTORY_LIMIT:]

    # ==================== Modo "prompted" (padrão) ====================
    # O catálogo de ferramentas fica DENTRO do prompt de sistema fixo. Ele é
    # processado uma vez (aquecimento) e reaproveitado do cache em todo pedido:
    # cada comando só processa a mensagem nova. No modo nativo do Ollama, o
    # template do llama3.1 muda o bloco de sistema quando há ferramentas e
    # invalida o cache (20-40 s por chamada na CPU).

    def catalog(self) -> str:
        lines = []
        for t in self.tools:
            fn = t["function"]
            name = fn["name"]
            spec = get_tool(name)
            params = []
            if spec is not None:
                for pname, prm in inspect.signature(spec.function).parameters.items():
                    if prm.kind in (prm.VAR_KEYWORD,):
                        continue
                    opt = prm.default is not inspect.Parameter.empty or prm.kind is prm.VAR_POSITIONAL
                    params.append(f"{pname}{'?' if opt else ''}")
            lines.append(f"- {name}({', '.join(params)}): {fn['description']}")
        return "\n".join(lines)

    def full_system(self, persona: str) -> str:
        if self.tool_mode != "prompted" or not self.tools:
            return persona
        if self._catalog_cache is None:
            self._catalog_cache = self.catalog()
        return persona + """

COMO AGIR
Para executar QUALQUER ação ou consultar dados do PC, celular, rede ou casa, responda APENAS com uma
linha JSON, sem nenhum texto antes ou depois:
{"tool": "nome_da_ferramenta", "args": {"parametro": "valor"}}
Você receberá o RESULTADO e então responderá ao usuário em texto normal, com base nele.
NUNCA diga "feito", "executado" ou invente um resultado sem ter recebido o RESULTADO de uma ferramenta.
Se não precisar de ferramenta (conversa, conhecimento geral), responda direto em texto (nunca JSON).
Parâmetros com ? são opcionais.

FERRAMENTAS
""" + self._catalog_cache + """

EXEMPLOS
Usuário: quanto de memória o PC está usando? -> {"tool": "hardware_info", "args": {}}
Usuário: abre o spotify -> {"tool": "launch_app", "args": {"name": "spotify"}}
Usuário: qual a bateria do celular? -> {"tool": "adb_get_battery", "args": {}}
Usuário: execute no powershell o comando Get-Date -> {"tool": "run_powershell", "args": {"command": "Get-Date"}}
Usuário: desligue o computador -> {"tool": "power_control", "args": {"action": "shutdown"}}
Usuário: quais aparelhos estão na rede? -> {"tool": "lan_devices", "args": {}}
Usuário: quem é você? -> Sou o J.A.R.V.I.S., seu sistema pessoal."""

    @staticmethod
    def _parse_action(text: str) -> Optional[tuple[str, dict]]:
        """Extrai {"tool": ..., "args": ...} (aceita variações comuns do modelo)."""
        start = text.find("{")
        while start != -1:
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                start = text.find("{", start + 1)
                continue
            if isinstance(obj, dict):
                fn = obj.get("function")
                if isinstance(fn, dict):  # {"function": {"name": ..., "arguments": ...}}
                    obj = {**obj, **fn}
                    fn = None
                name = obj.get("tool") or obj.get("name") or fn
                args = obj.get("args") or obj.get("arguments") or obj.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if isinstance(name, str) and name:
                    return name, args if isinstance(args, dict) else {}
            start = text.find("{", start + 1)
        return None

    async def _stream_text_or_action(self, session, model, messages, action_box: list) -> AsyncGenerator[str, None]:
        """Faz streaming do texto ao usuário; se a resposta for uma ação JSON, não fala
        nada dela e devolve a ação em action_box."""
        full = ""
        spoken = 0          # quanto de `full` já foi entregue
        mode = None         # None = indefinido, "text", "json"
        async for token in self._stream_chat(session, model, messages, [], []):
            full += token
            if mode is None:
                stripped = full.lstrip()
                if not stripped:
                    continue
                mode = "json" if stripped[0] in "{`" else "text"
            if mode == "text":
                # Segura o texto a partir de um "{" (pode ser uma ação no meio da frase)
                brace = full.find("{", spoken)
                safe_end = brace if brace != -1 else len(full)
                if safe_end > spoken:
                    yield full[spoken:safe_end]
                    spoken = safe_end
        action = self._parse_action(full)
        if action is None and mode == "json":
            # JSON quebrado (ex.: {"tool": "hardware_info", "args": {"ram"}}): recupera o nome
            m = re.search(r'"(?:tool|name)"\s*:\s*"([\w-]+)"', full)
            if m and get_tool(m.group(1)) is not None:
                action = (m.group(1), {})
        if action:
            action_box.append((action, full))
            return
        if mode == "json":
            # Resposta em JSON que não é ação válida: não lê símbolos em voz alta
            text = re.sub(r"[{}\[\]\"`]|json", " ", full)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                yield text
            return
        if spoken < len(full):
            yield full[spoken:]

    async def respond_prompted(self, text: str, persona: str, use_tools: bool) -> AsyncGenerator[str, None]:
        # Conversa pura (nenhum grupo de ferramentas casou) vai para o modelo de chat,
        # menor e mais rápido, sem o catálogo de ferramentas no prompt.
        if use_tools and self.chat_model != self.model and not select_tool_names(text):
            use_tools = False
        model = self.model if use_tools else self.chat_model
        system = self.full_system(persona) if use_tools else persona
        now = datetime.now()
        stamped = f"{text}\n(agora: {now:%H:%M}, {WEEKDAYS_SHORT[now.weekday()]} {now:%d/%m/%Y})"
        self._append({"role": "user", "content": stamped})

        answer_parts: list[str] = []
        timeout = aiohttp.ClientTimeout(total=300, sock_read=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Pedido com cara de ação: segura a 1ª resposta em texto para checar se o
                # modelo não "fingiu" ter executado algo sem chamar ferramenta.
                actionish = use_tools and bool(select_tool_names(text))
                tool_used = retried = False
                for _ in range(MAX_TOOL_ROUNDS + 1):
                    messages = [{"role": "system", "content": system}] + self.history
                    box: list = []
                    hold = actionish and not tool_used and not retried
                    held: list[str] = []
                    async for token in self._stream_text_or_action(session, model, messages, box):
                        if hold:
                            held.append(token)
                            continue
                        answer_parts.append(token)
                        yield token
                    if not box and hold:
                        reply = "".join(held).strip()
                        if _claims_action(reply):
                            print(f"[JARVIS] Resposta sem ferramenta descartada (alucinação): {reply[:80]}")
                            retried = True
                            self._append({"role": "assistant", "content": reply})
                            self._append({"role": "user", "content":
                                          "Você NÃO executou nenhuma ferramenta, então nada foi feito. "
                                          "Responda agora SOMENTE com o JSON da ferramenta adequada."})
                            continue
                        answer_parts.append(reply)
                        yield reply
                    if not box:
                        self._append({"role": "assistant", "content": "".join(answer_parts).strip()})
                        return
                    tool_used = True
                    (name, args), raw = box[0]
                    self._append({"role": "assistant", "content": raw.strip()})
                    result = await execute_tool(self.router, name, args, self.dangerous, self.confirm)
                    if result.get("cancelled"):
                        msg = "Como desejar. A ação não foi executada."
                        answer_parts.append(msg)
                        self._append({"role": "user", "content": f"RESULTADO de {name}: cancelado pelo usuário."})
                        self._append({"role": "assistant", "content": msg})
                        yield msg
                        return
                    self._append({"role": "user", "content":
                                  f"RESULTADO de {name}: {compact_result(result)}\n"
                                  "Responda ao usuário em texto, com base nesse resultado (ou use outra ferramenta se precisar)."})
                msg = "Receio que a tarefa exigiu passos demais. Pode detalhar o pedido?"
                yield msg
                self._append({"role": "assistant", "content": msg})
        except asyncio.CancelledError:
            self._append({"role": "assistant", "content": ("".join(answer_parts).strip() or "") + " (interrompido)"})
            raise

    def _append(self, msg: dict) -> None:
        """Histórico só cresce (preserva o cache de prefixo); quando estoura, corta pela metade."""
        self.history.append(msg)
        if len(self.history) > HISTORY_LIMIT * 2:
            self.history = self.history[-HISTORY_LIMIT:]
            while self.history and self.history[0]["role"] != "user":
                self.history.pop(0)

    def reset(self) -> None:
        self.history.clear()
        self._last_selected = set()


def _short(desc: str, limit: int = 110) -> str:
    """1ª frase da descrição: cada token conta (CPU processa ~35 tokens/s)."""
    desc = " ".join(desc.split())
    first = desc.split(". ")[0]
    return (first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0]).rstrip(".")


def _clean_schema(schema: dict) -> dict:
    """Esquema mínimo: sem descrições de parâmetros nem 'default' (menos tokens, menos confusão)."""
    schema = json.loads(json.dumps(schema))
    for prop in (schema.get("properties") or {}).values():
        if isinstance(prop, dict):
            prop.pop("default", None)
            prop.pop("description", None)
            prop.pop("title", None)
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


_NOISE_KEYS = {"position", "size", "hwnd", "pid_list", "raw", "bbox", "region", "image", "image_base64",
               "base64", "thumbnail", "attributes", "left", "top", "width", "height", "x", "y"}


def compact_result(result, limit: int = 700) -> str:
    """Resume o resultado da ferramenta para o modelo: tira coordenadas, imagens e
    listas enormes. Menos tokens = resposta final muito mais rápida na CPU."""
    def slim(v, depth=0):
        if isinstance(v, dict):
            return {k: slim(x, depth + 1) for k, x in v.items() if k not in _NOISE_KEYS}
        if isinstance(v, list):
            head = v[:12]
            # Lista de objetos (janelas, processos, dispositivos): só o identificador principal
            if head and all(isinstance(x, dict) for x in head):
                for key in ("title", "name", "Name", "label", "entity_id", "serial", "ip", "path"):
                    if all(key in x for x in head):
                        items = [str(x[key])[:60] for x in head if str(x.get(key, "")).strip()]
                        break
                else:
                    items = [slim(x, depth + 1) for x in head]
            else:
                items = [slim(x, depth + 1) for x in head]
            if len(v) > 12:
                items.append(f"... (+{len(v) - 12})")
            return items
        if isinstance(v, str) and len(v) > 400:
            return v[:400] + "..."
        return v
    text = json.dumps(slim(result), ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "...}"


CANCELLED_MSG = "CANCELADO pelo usuário. A ação NÃO foi executada e não há resultado."


_CLAIM_RE = re.compile(
    r"\b(feito|pronto|execut\w*|conclu\w*|resultado|abrindo|abri|aberto|liguei|desliguei|enviei|"
    r"apaguei|fechei|ativei|desativei|configurei|instalei|retornou|aqui est[aá])\b", re.I)


def _claims_action(reply: str) -> bool:
    """O texto afirma ter feito algo/obtido um resultado?"""
    return bool(_CLAIM_RE.search(reply or ""))


def _split_varargs(fn, args: dict) -> tuple[list, dict]:
    """Ferramentas com *args (ex.: hotkey(*keys)) recebem a lista como posicional."""
    for name, param in inspect.signature(fn).parameters.items():
        if param.kind is inspect.Parameter.VAR_POSITIONAL and name in args:
            args = dict(args)
            val = args.pop(name)
            if isinstance(val, str):
                val = [k.strip() for k in val.replace("+", ",").split(",") if k.strip()]
            return list(val or []), args
    return [], args


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
        pos, kw = _split_varargs(spec.function, args)
        if inspect.iscoroutinefunction(spec.function):
            result = await spec.function(*pos, **kw)
        else:
            result = await loop.run_in_executor(None, lambda: spec.function(*pos, **kw))
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
        from core.reflexes import Reflexes
        self.reflexes = Reflexes(personality.user_title) if self.config.get("reflexes", True) else None

        self.ollama = OllamaToolAgent(
            host=self.config.get("ollama_host", "http://localhost:11434"),
            model=self.config.get("ollama_model", "llama3.1:8b"),
            tools=self.voice_tools,
            router=self.router,
            dangerous=self.needs_confirm,
            chat_model=self.config.get("ollama_chat_model", ""),
            keep_alive=str(self.config.get("ollama_keep_alive", "30m")),
            tool_mode=str(self.config.get("ollama_tool_mode", "prompted")),
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

    def system_prompt(self, spoken: bool, compact: bool = False) -> str:
        """Prompt ESTÁTICO (sem hora) para o Ollama reaproveitar o cache de prefixo.
        compact = versão enxuta para modelos locais (menos tokens = resposta mais rápida)."""
        persona = self.personality.get_system_prompt_injection(spoken=spoken, compact=compact)
        if compact:
            return persona
        return persona + "\n\n" + SYSTEM_PROMPT.strip()

    async def warmup(self) -> None:
        if self.engine == "ollama":
            await self.ollama.warmup(self.system_prompt(spoken=True, compact=True))

    async def respond(self, text: str, spoken: bool = True) -> AsyncGenerator[str, None]:
        """Gera a resposta (em pedaços). Reflexos primeiro; depois IA com fallback."""
        if self.reflexes is not None:
            reply = await self.reflexes.handle(text)
            if reply:
                # Mantém o contexto para follow-ups ("agora feche ele")
                self.ollama.history += [{"role": "user", "content": text},
                                        {"role": "assistant", "content": reply}]
                yield reply
                return
        async for token in self._respond_ai(text, spoken):
            yield token

    async def _respond_ai(self, text: str, spoken: bool) -> AsyncGenerator[str, None]:
        use_tools = bool(self.config.get("voice_tools", True))
        order = [self.engine] + [e for e in ("ollama", "gemini") if e != self.engine]
        last_error: Optional[Exception] = None
        yielded = False

        for engine in order:
            if engine == "gemini" and self.brain is None:
                continue
            try:
                if engine == "ollama":
                    self.ollama.confirm = self.confirm
                    self.ollama.max_tokens = 110 if spoken else None
                    stream = (self.ollama.respond_prompted if self.ollama.tool_mode == "prompted"
                              else self.ollama.respond_stream)
                    async for token in stream(text, self.system_prompt(spoken, compact=True), use_tools):
                        yielded = True
                        yield token
                else:
                    async for token in self.brain.think(
                        text,
                        use_tools=use_tools,
                        tool_names=[t["name"] for t in self.voice_tools],
                        spoken=spoken,
                        tool_executor=self._execute,
                    ):
                        yielded = True
                        yield token
                if engine != self.engine:
                    print(f"[JARVIS] Motor alternado para {engine}")
                    self.engine = engine
                return
            except Exception as e:
                last_error = e
                print(f"[JARVIS] Motor {engine} falhou: {e}")
                if yielded:
                    raise  # já falou parte da resposta; não repete com outro motor
        raise RuntimeError(f"Todos os motores falharam: {last_error}")

    async def _execute(self, name: str, args: dict) -> dict:
        return await execute_tool(self.router, name, args, self.needs_confirm, self.confirm)

    def reset(self) -> None:
        self.ollama.reset()
        if self.brain:
            self.brain.reset()
