"""
JarvisVoiceAssistant - experiência de voz estilo filme.

  [espera] -- "Jarvis" (detector dedicado) / 2 palmas --> overlay aparece
  [comando] -> reflexo instantâneo OU IA (streaming) -> fala frase a frase
            (a próxima frase é sintetizada enquanto a atual toca)
  [falando] "Jarvis!" a qualquer momento -> interrompe na hora (barge-in)
  [janela de conversa] follow-ups sem repetir o nome -> silêncio -> espera

Ações sensíveis só executam após confirmação por voz ("sim" / "confirmo").
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

import numpy as np
import os

DEBUG = bool(os.environ.get('JARVIS_DEBUG'))

from config.settings import load_config
from core.jarvis_agent import JarvisAgent, system_report, time_greeting
from core.personality import Personality
from gui.overlay_client import OverlayClient
from voice.listener import ListenerConfig, Utterance, VoiceListener
from voice.player import AudioPlayer, chime
from voice.stt import FasterWhisperSTT, ModelSize, STTConfig, detect_wake_word, wake_in_text
from voice.tts_hybrid import TTSConfig, TTSProvider, get_hybrid_tts

YES = ("sim", "confirmo", "confirma", "pode", "afirmativo", "prossiga", "manda", "autorizo", "claro", "faca", "faça")
NO = ("nao", "não", "cancela", "cancelar", "negativo", "espera", "pare", "aborta")
STOP_WORDS = {"pare", "para", "chega", "silencio", "cancela", "cancelar", "esquece", "deixa", "ok", "tudo bem",
              "pode parar", "cala a boca", "quieto"}

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
    import unicodedata
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", "", text).strip()


def speakable(text: str) -> str:
    """Remove Markdown, URLs e símbolos que soam mal na fala."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "o link", text)
    text = re.sub(r"[*_#>|~{}]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(buf: str, first: bool) -> tuple[list[str], str]:
    """Separa frases completas do buffer. A primeira pode ser cortada na vírgula
    (se longa) para o JARVIS começar a falar mais cedo."""
    out = []
    while True:
        m = re.search(r"(.+?[.!?…])(\s+|$)", buf, flags=re.S)
        if first and not out and not m:
            c = re.search(r"^(.{60,}?,)\s+(?=.{25,})", buf, flags=re.S)
            if c:
                out.append(c.group(1).strip())
                buf = buf[c.end():]
                continue
        if not m:
            return out, buf
        out.append(m.group(1).strip())
        buf = buf[m.end():]


class JarvisVoiceAssistant:
    def __init__(self, personality: Personality, config: Optional[dict] = None, show_overlay: bool = True):
        self.config = config or load_config()
        self.p = personality
        self.title = personality.user_title
        self.window = float(self.config.get("conversation_window", 8.0))
        self.wake_word = self.config.get("wake_word", "jarvis")
        self.barge_in = bool(self.config.get("barge_in", True))

        self.agent = JarvisAgent(personality, self.config)
        self.agent.confirm = self.confirm_action
        self.overlay = OverlayClient(enabled=show_overlay)

        size = str(self.config.get("stt_model", "small")).lower()
        try:
            model_size = ModelSize(size)
        except ValueError:
            model_size = ModelSize.SMALL
        self.stt = FasterWhisperSTT(STTConfig(model_size=model_size))
        self.listener = VoiceListener(ListenerConfig(
            wake_word=self.wake_word,
            wake_model=str(self.config.get("wake_model", "tiny")),
            vad_threshold=float(self.config.get("vad_threshold", 0.5)),
        ))
        self.player = AudioPlayer()
        self.tts = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._speech_lock = asyncio.Lock()
        self._answer_task: Optional[asyncio.Task] = None
        self._clap = asyncio.Event()
        self._interrupted = False
        self._confirming = False
        self.use_microphone = True
        self._recent_speech: list[str] = []
        self._tts_cache: dict = {}

    # ==================== Inicialização ====================
    async def boot(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.overlay.start()
        self.overlay.send("online", "Inicializando sistemas...")

        self.tts = await get_hybrid_tts(TTSConfig(
            primary=TTSProvider(self.config.get("tts_primary", "kokoro")),
            kokoro_voice=self.config.get("kokoro_voice", "pm_alex"),
            edge_voice=self.config.get("edge_voice", "pt-BR-AntonioNeural"),
            edge_rate=self.config.get("edge_rate", "-4%"),
            edge_pitch=self.config.get("edge_pitch", "-8Hz"),
        ))

        print("[JARVIS] Carregando reconhecimento de fala e detector de wake word...")
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            loop.run_in_executor(None, self.stt.load_model),
            loop.run_in_executor(None, self.listener.load),
        )
        await self.agent.initialize()

        self.listener.on_wake = self._on_wake
        self.listener.start(loop, use_microphone=self.use_microphone)

        # Pré-carrega a IA em segundo plano enquanto cumprimenta
        warm = asyncio.create_task(self.agent.warmup())
        asyncio.create_task(self._precache_phrases())
        await self.say(f"{time_greeting(self.title)} {system_report(self.title)}")
        self.overlay.hide()
        if not warm.done():
            print("[JARVIS] Aquecendo a IA local em segundo plano (primeira resposta pode demorar um pouco)...")

    # ==================== Eventos de ativação ====================
    def _on_wake(self) -> None:
        """Wake word detectado (thread do loop)."""
        busy = self.player.playing or (self._answer_task is not None and not self._answer_task.done())
        if busy and self.barge_in:
            print("[JARVIS] Interrompido pelo usuário.")
            self.interrupt()
        self.overlay.listening()

    def on_double_clap(self) -> None:
        """Chamado pela thread do detector de palmas."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._clap_wake)

    def _clap_wake(self) -> None:
        if self.player.playing:
            self.interrupt()
        self._clap.set()

    def interrupt(self) -> None:
        self._interrupted = True
        self.player.stop()
        if self._answer_task and not self._answer_task.done():
            self._answer_task.cancel()
        self.listener.end_speaking()

    # ==================== Fala ====================
    async def _play(self, samples: np.ndarray, sr: int, text: str, state: str = "speaking") -> bool:
        async with self._speech_lock:
            # O listener usa isso para ignorar o próprio eco e o próprio nome
            self.listener.begin_speaking(text.replace("J.A.R.V.I.S.", "Jarvis"))
            self._recent_speech.append(text)
            self._recent_speech = self._recent_speech[-4:]
            self.overlay.send(state, text)
            try:
                return await self.player.play(samples, sr)
            finally:
                self.listener.end_speaking()

    async def synth(self, text: str):
        """Síntese com cache para frases curtas e repetidas (resposta instantânea)."""
        if text in self._tts_cache:
            return self._tts_cache[text]
        audio = await self.tts.synthesize(text)
        if len(text) <= 48:
            self._tts_cache[text] = audio
        return audio

    async def _precache_phrases(self) -> None:
        p = self.p
        phrases = {p._fill(x) for x in (p.acknowledgements + p.thinking + p.confirmations + p.standby)}
        phrases |= {"Executando.", "Pausado.", "Retomando.", "Próxima faixa.", "Faixa anterior."}
        for text in phrases:
            try:
                await self.synth(speakable(text))
            except Exception:
                pass

    async def say(self, text: str, state: str = "speaking") -> bool:
        text = speakable(text)
        if not text:
            return True
        print(f"JARVIS: {text}")
        try:
            samples, sr = await self.synth(text)
        except Exception as e:
            print(f"[JARVIS] TTS falhou: {e}")
            return True
        return await self._play(samples, sr, text, state)

    # ==================== Confirmação por voz ====================
    async def confirm_action(self, tool: str, args: dict) -> bool:
        label = TOOL_LABELS.get(tool, f"usar a ferramenta {tool.replace('_', ' ')}")
        detail = ", ".join(f"{k}: {v}" for k, v in (args or {}).items())[:180]
        print(f"[JARVIS] Confirmação necessária: {tool} {args}")
        self._confirming = True
        try:
            await self.say(f"Isso requer sua autorização, {self.title}: {label}. Confirma?", state="confirm")
            self.overlay.confirm(f"{label}\n{detail}")
            answer = await self.next_command(timeout=8.0, capture=True)
        finally:
            self._confirming = False
        approved = False
        if answer:
            n = _norm(answer)
            words = n.split()
            if not any(w in words or n.startswith(w) for w in NO):
                approved = any(w in words or n.startswith(w) for w in YES)
        print(f"[JARVIS] Confirmação: '{answer}' -> {'APROVADA' if approved else 'NEGADA'}")
        self.overlay.thinking()
        if approved:
            await self.say("Executando.")
            self.overlay.thinking()
        return approved

    # ==================== Escuta ====================
    async def transcribe(self, utt: Utterance) -> Optional[str]:
        text = await self.stt.transcribe_audio(utt.audio)
        return text.strip() if text and text.strip() else None

    async def next_command(self, timeout: Optional[float], capture: bool) -> Optional[str]:
        """Espera a próxima fala-comando (ou None no timeout)."""
        self.listener.flush()
        self.listener.set_capture(capture)
        try:
            utt = await asyncio.wait_for(self.listener.commands.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.listener.set_capture(False)
        return await self.transcribe(utt)

    # ==================== Resposta (pipeline) ====================
    async def answer(self, text: str) -> None:
        """IA/reflexo -> frases -> síntese (adiantada) -> reprodução interrompível."""
        self.overlay.thinking()
        sentences: asyncio.Queue = asyncio.Queue()
        audio_q: asyncio.Queue = asyncio.Queue(maxsize=2)

        async def produce():
            buf, first = "", True
            try:
                async for chunk in self.agent.respond(text, spoken=True):
                    buf += chunk
                    done, buf = split_sentences(buf, first)
                    for s in done:
                        first = False
                        await sentences.put(s)
                if buf.strip():
                    await sentences.put(buf.strip())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[JARVIS] Erro: {e}")
                await sentences.put(f"{self.p.get_error()} Os motores de IA não responderam.")
            finally:
                await sentences.put(None)

        async def synthesize():
            filler_used = False
            try:
                while True:
                    try:
                        s = await asyncio.wait_for(sentences.get(), timeout=None if filler_used else 3.0)
                    except asyncio.TimeoutError:
                        # A IA está demorando: fala algo, como no filme
                        filler_used = True
                        if not self._confirming:
                            s = self.p.get_thinking()
                            await audio_q.put((s, *(await self.synth(s))))
                        continue
                    if s is None:
                        break
                    filler_used = True
                    s = speakable(s)
                    if not s:
                        continue
                    try:
                        samples, sr = await self.synth(s)
                    except Exception as e:
                        print(f"[JARVIS] TTS falhou: {e}")
                        continue
                    await audio_q.put((s, samples, sr))
            finally:
                await audio_q.put(None)

        producer = asyncio.create_task(produce())
        synth = asyncio.create_task(synthesize())
        caption, spoke = "", False
        try:
            while True:
                item = await audio_q.get()
                if item is None:
                    break
                sentence, samples, sr = item
                if DEBUG and not spoke and getattr(self, "_t_cmd", None):
                    print(f"[Tempo] comando -> 1º áudio pronto: {time.monotonic() - self._t_cmd:.2f}s")
                caption = (caption + " " + sentence).strip()[-260:]
                print(f"JARVIS: {sentence}")
                spoke = True
                if not await self._play(samples, sr, caption):
                    raise asyncio.CancelledError()
            if not spoke:
                await self.say(self.p.get_confirmation())
        finally:
            for task in (producer, synth):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer, synth, return_exceptions=True)

    # ==================== Comandos especiais ====================
    def is_echo(self, text: str) -> bool:
        """Transcrição parecida com algo que o JARVIS acabou de falar = eco da sala."""
        import difflib
        n = _norm(text)
        if len(n) < 4:
            return False
        for said in self._recent_speech:
            s = _norm(said)
            if n in s or difflib.SequenceMatcher(None, n, s).ratio() > 0.6:
                return True
        return False

    def is_dismiss(self, text: str) -> bool:
        return _norm(text) in {"obrigado", "valeu", "isso e tudo", "so isso", "dispensado", "pode ir",
                               "modo espera", "pode descansar", "nada", "obrigado jarvis"}

    def is_shutdown(self, text: str) -> bool:
        n = _norm(text)
        return any(k in n for k in ("desliguese", "desligue se", "encerrar sistemas", "protocolo de desligamento",
                                    "encerre o jarvis", "desligar jarvis", "desativese", "desative se"))

    # ==================== Loop principal ====================
    async def run(self) -> None:
        await self.boot()
        self._running = True
        awake_until = 0.0
        print(f"\nSistema de voz ativo. Diga '{self.wake_word}' ou bata 2 palmas. Ctrl+C para sair.\n")

        while self._running:
            awake = time.time() < awake_until

            # Espera: comando (fala) OU palmas OU fim da janela de conversa
            self.listener.set_capture(awake)
            get_cmd = asyncio.create_task(self.listener.commands.get())
            get_clap = asyncio.create_task(self._clap.wait())
            timeout = max(0.5, awake_until - time.time()) if awake else None
            done, _ = await asyncio.wait({get_cmd, get_clap}, timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            for t in (get_cmd, get_clap):
                if t not in done:
                    t.cancel()
            self.listener.set_capture(False)

            if get_clap in done:
                self._clap.clear()
                if get_cmd in done:  # devolve a fala que chegou junto
                    self.listener.commands.put_nowait(get_cmd.result())
                self.overlay.listening()
                await self._play(chime(), 24000, "")
                await self.say(self.p.get_acknowledgement(), state="listening")
                self.overlay.listening()
                awake_until = time.time() + self.window
                continue

            if not done:  # janela de conversa acabou
                print("[JARVIS] Modo espera.")
                self.overlay.hide()
                awake_until = 0.0
                continue

            utt: Utterance = get_cmd.result()
            t_cmd = time.monotonic()
            text = await self.transcribe(utt)
            self._t_cmd = t_cmd
            if DEBUG:
                print(f"[Tempo] transcrição: {time.monotonic() - t_cmd:.2f}s")
            if not text:
                if not awake:
                    self.overlay.hide()
                continue
            print(f"Você: {text}")

            if self.is_echo(text):
                print("[JARVIS] Eco da própria voz ignorado.")
                continue

            found, rest = detect_wake_word(text, self.wake_word)
            if not found and utt.woke:
                # O detector rápido suspeitou de "Jarvis", mas a transcrição precisa não confirma
                found = wake_in_text(text, self.wake_word)
                if not found:
                    print("[JARVIS] Falso alarme do wake word, ignorado.")
                    if not awake:
                        self.overlay.hide()
                    continue
            if found:
                text = rest
            elif not awake:
                continue

            if not text:
                self.overlay.listening()
                await self.say(self.p.get_acknowledgement(), state="listening")
                self.overlay.listening()
                awake_until = time.time() + self.window
                continue

            self.overlay.user(text)
            n = _norm(text)

            if self.is_shutdown(text):
                await self.say(self.p.get_farewell())
                break
            if n in STOP_WORDS:
                # "Jarvis, pare" -> já interrompeu; só fica ouvindo
                self.overlay.listening()
                awake_until = time.time() + self.window
                continue
            if self.is_dismiss(text):
                await self.say(self.p.get_standby())
                self.overlay.hide()
                awake_until = 0.0
                continue

            self._interrupted = False
            self._answer_task = asyncio.create_task(self.answer(text))
            try:
                await self._answer_task
            except asyncio.CancelledError:
                if not self._interrupted:
                    raise
            finally:
                self._answer_task = None

            await asyncio.sleep(0.25)  # deixa o eco da própria voz morrer
            if not self._interrupted:
                self.listener.flush()
            self.overlay.listening()
            awake_until = time.time() + self.window

        await self.shutdown()

    async def shutdown(self) -> None:
        self._running = False
        self.player.stop()
        self.listener.stop()
        self.overlay.stop()
