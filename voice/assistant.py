"""
JarvisVoiceAssistant - experiência de voz estilo filme.

Fluxo:
  [espera] --"Jarvis" / 2 palmas--> overlay aparece + "Sim, senhor?"
  [acordado] comando -> pensa (overlay dourado) -> responde falando, frase a frase
  continua ouvindo por `conversation_window` segundos (sem precisar dizer "Jarvis")
  silêncio -> volta ao modo espera e o overlay some.

Ações sensíveis (PowerShell, desligar PC, apagar arquivo, comandos no celular...)
só executam após confirmação por voz ("sim" / "confirmo").
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Optional

from config.settings import load_config
from core.jarvis_agent import JarvisAgent, system_report, time_greeting
from core.personality import Personality
from gui.overlay_client import OverlayClient
from voice.stt import FasterWhisperSTT, STTConfig, ModelSize, detect_wake_word
from voice.tts_hybrid import get_hybrid_tts, TTSConfig, TTSProvider

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]

YES = ("sim", "confirmo", "confirma", "pode", "afirmativo", "prossiga", "manda", "autorizo", "claro", "faça", "faca")
NO = ("não", "nao", "cancela", "cancelar", "negativo", "espera", "pare", "aborta")

TOOL_LABELS = {
    "run_powershell": "executar um comando no PowerShell",
    "power_control": "alterar o estado de energia do computador",
    "kill_process": "encerrar um processo",
    "delete_file": "apagar um arquivo",
    "write_file": "gravar um arquivo",
    "registry_edit": "alterar o registro do Windows",
    "manage_service": "alterar um serviço do Windows",
    "android_shell": "executar um comando no celular",
    "android_communication": "fazer uma ligação ou enviar mensagem pelo celular",
    "network_ssh_exec": "executar um comando remoto via SSH",
    "device_network_command": "enviar um comando a outro dispositivo da rede",
    "unlock_pc": "acordar e desbloquear a tela",
}


def _norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def speakable(text: str) -> str:
    """Remove Markdown, URLs e símbolos que soam mal na fala."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "o link", text)
    text = re.sub(r"[*_#>|~]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


class JarvisVoiceAssistant:
    def __init__(self, personality: Personality, config: Optional[dict] = None, show_overlay: bool = True):
        self.config = config or load_config()
        self.p = personality
        self.title = personality.user_title
        self.window = float(self.config.get("conversation_window", 8.0))
        self.wake_word = self.config.get("wake_word", "jarvis")

        self.agent = JarvisAgent(personality, self.config)
        self.agent.confirm = self.confirm_action
        self.overlay = OverlayClient(enabled=show_overlay)

        size = str(self.config.get("stt_model", "small")).lower()
        try:
            model_size = ModelSize(size)
        except ValueError:
            model_size = ModelSize.SMALL
        self.stt = FasterWhisperSTT(STTConfig(model_size=model_size))
        self.tts = None

        self._running = False
        self._last_spoke = 0.0
        self._tts_lock = asyncio.Lock()
        self._clap = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ==================== Inicialização ====================
    async def boot(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.overlay.start()
        self.overlay.send("online", "Inicializando sistemas...")

        tts_cfg = TTSConfig(
            primary=TTSProvider(self.config.get("tts_primary", "kokoro")),
            kokoro_voice=self.config.get("kokoro_voice", "pm_alex"),
            edge_voice=self.config.get("edge_voice", "pt-BR-AntonioNeural"),
            edge_rate=self.config.get("edge_rate", "-4%"),
            edge_pitch=self.config.get("edge_pitch", "-8Hz"),
        )
        self.tts = await get_hybrid_tts(tts_cfg)

        print("[JARVIS] Carregando reconhecimento de fala (o primeiro uso baixa o modelo)...")
        await asyncio.get_running_loop().run_in_executor(None, self.stt.load_model)
        await self.agent.initialize()

        greeting = f"{time_greeting(self.title)} {system_report(self.title)}"
        await self.say(greeting)
        self.overlay.hide()

    def on_double_clap(self) -> None:
        """Chamado pela thread do detector de palmas."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._clap.set)
            self.stt._abort = True  # interrompe a escuta atual para responder já

    # ==================== Fala ====================
    async def say(self, text: str, state: str = "speaking") -> None:
        text = speakable(text)
        if not text:
            return
        print(f"JARVIS: {text}")
        async with self._tts_lock:
            self.overlay.send(state, text)
            try:
                await self.tts.speak(text, blocking=True)
            finally:
                self._last_spoke = time.time()

    async def listen(self, timeout: float) -> Optional[str]:
        started = time.time()
        self.stt._listening = True
        text = await self.stt.listen_once(timeout=timeout)
        # Se o JARVIS falou enquanto gravávamos, o áudio é a própria voz dele
        if text and self._last_spoke > started:
            return None
        return text

    # ==================== Confirmação por voz ====================
    async def confirm_action(self, tool: str, args: dict) -> bool:
        label = TOOL_LABELS.get(tool, f"usar a ferramenta {tool.replace('_', ' ')}")
        detail = ", ".join(f"{k}: {v}" for k, v in (args or {}).items())[:180]
        print(f"[JARVIS] Confirmação necessária: {tool} {args}")
        await self.say(f"Isso requer sua autorização, {self.title}: {label}. Confirma?", state="confirm")
        self.overlay.confirm(f"{label}\n{detail}")
        for _ in range(2):
            answer = await self.listen(timeout=8.0)
            if not answer:
                break
            n = _norm(answer)
            if any(w in n.split() or n.startswith(w) for w in NO):
                break
            if any(w in n.split() or n.startswith(w) for w in YES):
                self.overlay.thinking()
                await self.say("Executando.")
                self.overlay.thinking()
                return True
        self.overlay.thinking()
        return False

    # ==================== Intenções instantâneas ====================
    def local_intent(self, text: str) -> Optional[str]:
        n = _norm(text)
        now = datetime.now()
        if re.search(r"\b(que horas|que hora|horas sao)\b", n):
            return f"São {now.hour} e {now.minute:02d}, {self.title}." if now.minute else f"São {now.hour} em ponto, {self.title}."
        if re.search(r"\b(que dia|data de hoje|dia e hoje)\b", n):
            return f"Hoje é {WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]}."
        if re.search(r"\b(status|diagnostico|relatorio|como (esta|estao) o(s)? sistema)", n):
            return system_report(self.title)
        return None

    def is_dismiss(self, text: str) -> bool:
        n = _norm(text)
        return n in {"obrigado", "valeu", "isso e tudo", "so isso", "dispensado", "pode ir", "modo espera",
                     "pode descansar", "nada", "deixa", "esquece"}

    def is_shutdown(self, text: str) -> bool:
        n = _norm(text)
        return any(k in n for k in ("desliguese", "desligue se", "encerrar sistemas", "protocolo de desligamento",
                                    "encerre o jarvis", "desligar jarvis", "desative se"))

    # ==================== Resposta do agente (streaming por frase) ====================
    async def answer(self, text: str) -> None:
        self.overlay.thinking()
        sentences: asyncio.Queue = asyncio.Queue()
        spoken_any = False

        async def producer():
            buf = ""
            try:
                async for chunk in self.agent.respond(text, spoken=True):
                    buf += chunk
                    while True:
                        m = re.search(r"(.+?[.!?…])(\s+|$)", buf, flags=re.S)
                        if not m or (m.end() == len(buf) and not chunk.endswith((" ", "\n"))):
                            break
                        await sentences.put(m.group(1).strip())
                        buf = buf[m.end():]
                if buf.strip():
                    await sentences.put(buf.strip())
            except Exception as e:
                print(f"[JARVIS] Erro: {e}")
                await sentences.put(f"{self.p.get_error()} Os motores de IA não responderam.")
            finally:
                await sentences.put(None)

        task = asyncio.create_task(producer())
        caption = ""
        while True:
            sentence = await sentences.get()
            if sentence is None:
                break
            caption = (caption + " " + sentence).strip()[-260:]
            spoken_any = True
            async with self._tts_lock:
                self.overlay.speaking(caption)
                print(f"JARVIS: {sentence}")
                try:
                    await self.tts.speak(speakable(sentence), blocking=True)
                finally:
                    self._last_spoke = time.time()
        await task
        if not spoken_any:
            await self.say(self.p.get_confirmation())

    # ==================== Loop principal ====================
    async def run(self) -> None:
        await self.boot()
        self._running = True
        awake_until = 0.0
        print(f"\nSistema de voz ativo. Diga '{self.wake_word}' ou bata 2 palmas. Ctrl+C para sair.\n")

        while self._running:
            awake = time.time() < awake_until

            if self._clap.is_set():
                self._clap.clear()
                self.overlay.listening()
                await self.say(self.p.get_acknowledgement(), state="listening")
                self.overlay.listening()
                awake_until = time.time() + self.window
                continue

            timeout = max(1.0, awake_until - time.time()) if awake else 30.0
            text = await self.listen(timeout)

            if not text:
                if awake and time.time() >= awake_until:
                    print("[JARVIS] Modo espera.")
                    self.overlay.hide()
                continue

            print(f"Você: {text}")
            if not awake:
                found, rest = detect_wake_word(text, self.wake_word)
                if not found:
                    continue
                self.overlay.listening()
                if not rest:
                    await self.say(self.p.get_acknowledgement(), state="listening")
                    self.overlay.listening()
                    awake_until = time.time() + self.window
                    continue
                text = rest
            else:
                # Já acordado: remove "jarvis" se a pessoa repetir o nome
                found, rest = detect_wake_word(text, self.wake_word)
                if found and rest:
                    text = rest

            self.overlay.user(text)

            if self.is_shutdown(text):
                await self.say(self.p.get_farewell())
                break
            if self.is_dismiss(text):
                await self.say(self.p.get_standby())
                self.overlay.hide()
                awake_until = 0.0
                continue

            local = self.local_intent(text)
            if local:
                await self.say(local)
            else:
                await self.answer(text)

            self.overlay.listening()
            awake_until = time.time() + self.window

        await self.shutdown()

    async def shutdown(self) -> None:
        self._running = False
        self.stt.stop_listening()
        if self.tts:
            self.tts.stop()
        self.overlay.stop()
