"""
VoiceListener - escuta contínua com detecção dedicada do wake word.

Pipeline (thread própria, microfone sempre aberto):

    mic 16 kHz ──► Silero VAD (janelas de 30 ms) ──► segmentos de fala
                     │
                     ├─ modo espera / JARVIS falando:
                     │     Whisper *tiny* só em janelas de ~1,6 s da fala
                     │     ("Jarvis"?)  ──► on_wake()  (permite interromper)
                     │
                     └─ segmento com wake word ou janela de conversa ativa:
                           vira COMANDO ──► fila `commands` (áudio completo)

O Whisper "small" (preciso, mais lento) só roda no comando, nunca no áudio
ambiente. Ruídos (ventilador, teclado, música) não acordam nada: o VAD só
dispara com voz humana.
"""
from __future__ import annotations

import asyncio
import collections
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from voice.stt import wake_in_text

SR = 16000
DEBUG = bool(__import__('os').environ.get('JARVIS_DEBUG'))
FRAME = 480                  # 30 ms
FRAME_S = FRAME / SR


@dataclass
class ListenerConfig:
    wake_word: str = "jarvis"
    wake_model: str = "tiny"          # modelo Whisper só para o wake word
    vad_threshold: float = 0.5        # Silero: probabilidade de fala
    end_silence: float = 0.55         # silêncio que encerra uma frase (s)
    max_utterance: float = 15.0
    min_speech: float = 0.25          # descarta "pls", cliques, tosses
    wake_window: float = 1.6          # áudio analisado pelo tiny (s)
    wake_hop: float = 1.2             # nova checagem a cada X s de fala contínua
    rms_fallback_threshold: float = 0.012  # usado só se o VAD neural não carregar


@dataclass
class Utterance:
    audio: np.ndarray       # float32 16 kHz
    woke: bool              # True se o wake word foi detectado nesta fala
    duration: float


class VoiceListener:
    def __init__(self, config: Optional[ListenerConfig] = None):
        self.cfg = config or ListenerConfig()
        self.on_wake: Optional[Callable[[], None]] = None   # chamado na thread do loop asyncio
        self.commands: Optional[asyncio.Queue] = None

        # Estado controlado pelo assistente. Tudo é decidido pelo HORÁRIO DO ÁUDIO
        # (não pelo horário do processamento, que atrasa ~1 s durante a checagem do tiny).
        self._capture_since: Optional[float] = None      # janela de conversa ativa desde...
        self._speech_log: collections.deque = collections.deque(maxlen=20)  # [início, fim|None, texto]
        self.echo_tail = 0.45                            # reverberação após o JARVIS parar de falar

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._frames: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._vad = None
        self._tiny = None
        self._wake_lock = threading.Lock()   # tiny é usado só por esta thread

    # ==================== Ciclo de vida ====================
    def load(self) -> None:
        """Carrega VAD e Whisper tiny (bloqueante - rode em executor)."""
        try:
            from openwakeword.vad import VAD
            from openwakeword.utils import download_models
            try:
                self._vad = VAD()
            except Exception:
                download_models(model_names=["hey_jarvis"])  # baixa também o silero_vad.onnx
                self._vad = VAD()
            print("[Listener] VAD neural (Silero) carregado")
        except Exception as e:
            print(f"[Listener] VAD neural indisponível ({e}); usando energia do microfone")
            self._vad = None

        from faster_whisper import WhisperModel
        self._tiny = WhisperModel(self.cfg.wake_model, device="cpu", compute_type="int8")
        self._tiny.transcribe(np.zeros(SR // 2, np.float32), language="pt")  # aquece
        print(f"[Listener] Detector de wake word pronto (whisper-{self.cfg.wake_model})")

    def start(self, loop: asyncio.AbstractEventLoop, use_microphone: bool = True) -> None:
        self._loop = loop
        self.commands = asyncio.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._worker, name="jarvis-listener", daemon=True)
        self._thread.start()
        if use_microphone:
            import sounddevice as sd
            self._stream = sd.InputStream(
                samplerate=SR, channels=1, dtype="float32", blocksize=FRAME,
                callback=lambda indata, *_: self._frames.put((time.monotonic(), indata[:, 0].copy())),
            )
            self._stream.start()

    def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def feed(self, audio: np.ndarray) -> None:
        """Injeta áudio (16 kHz float32) - usado em testes sem microfone."""
        now = time.monotonic()
        for i in range(0, len(audio) - FRAME + 1, FRAME):
            self._frames.put((now, audio[i:i + FRAME].astype(np.float32)))

    # ---------- Estado vindo do assistente ----------
    def set_capture(self, on: bool) -> None:
        """Janela de conversa: falas que COMEÇAREM a partir de agora viram comando."""
        self._capture_since = time.monotonic() if on else None

    def begin_speaking(self, text: str) -> None:
        self._speech_log.append([time.monotonic(), None, text])

    def end_speaking(self) -> None:
        if self._speech_log and self._speech_log[-1][1] is None:
            self._speech_log[-1][1] = time.monotonic()

    @property
    def speaking(self) -> bool:
        return bool(self._speech_log) and self._speech_log[-1][1] is None

    def _jarvis_text_at(self, t: float) -> Optional[str]:
        """Texto que o JARVIS falava no instante t (incluindo a cauda de eco), ou None."""
        for start, end, text in reversed(self._speech_log):
            if start - 0.1 <= t <= (end if end is not None else float("inf")) + self.echo_tail:
                return text
        return None

    def flush(self) -> None:
        """Descarta comandos pendentes (ex.: áudio da própria voz do JARVIS)."""
        if self.commands:
            while not self.commands.empty():
                self.commands.get_nowait()

    # ==================== Detecção ====================
    def _is_speech(self, frame: np.ndarray) -> bool:
        if self._vad is not None:
            pcm = np.clip(frame * 32767, -32768, 32767).astype(np.int16)
            return float(self._vad.predict(pcm, frame_size=FRAME)) >= self.cfg.vad_threshold
        return float(np.sqrt(np.mean(frame ** 2))) >= self.cfg.rms_fallback_threshold

    def _check_wake(self, audio: np.ndarray, audio_time: float) -> bool:
        jarvis_said = self._jarvis_text_at(audio_time)
        if jarvis_said is not None and "jarvis" in jarvis_said.lower():
            return False  # o próprio JARVIS dizendo o nome
        echo = jarvis_said is not None
        segs, _ = self._tiny.transcribe(
            audio, language="pt", beam_size=1, without_timestamps=True,
            # Durante a fala dele, sem viés para "Jarvis" (evita alucinar o nome no eco)
            initial_prompt=None if echo else "Jarvis.", condition_on_previous_text=False,
        )
        text = " ".join(s.text for s in segs).strip()
        if not text:
            return False
        # Sobre o eco: só aceita o nome exato e se o texto não for a própria fala dele
        hit = wake_in_text(text, self.cfg.wake_word, fuzzy=not echo)
        if hit and echo:
            import difflib
            from voice.stt import _normalize
            similar = difflib.SequenceMatcher(None, _normalize(text), _normalize(jarvis_said)).ratio()
            if similar > 0.5:
                hit = False
        if hit:
            print(f"[Listener] Wake word{' (sobre a fala do JARVIS)' if echo else ''}: '{text}'")
        return hit

    def _emit(self, fn, *args) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(fn, *args)

    # ==================== Thread principal ====================
    def _worker(self) -> None:
        cfg = self.cfg
        pre_roll: collections.deque = collections.deque(maxlen=int(0.3 / FRAME_S))
        in_speech = False
        seg: list[np.ndarray] = []
        seg_start = 0.0        # horário (do áudio) em que a fala começou
        seg_t = 0.0            # horário do último quadro do segmento
        speech_frames = silence_frames = 0
        checked_at = 0.0       # duração do segmento na última checagem do wake word
        is_command = False
        woke = False

        while self._running:
            try:
                t, frame = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue

            speech = self._is_speech(frame)

            if not in_speech:
                pre_roll.append(frame)
                if speech:
                    in_speech = True
                    seg = list(pre_roll)
                    seg_start = t - len(pre_roll) * FRAME_S
                    speech_frames, silence_frames = 1, 0
                    checked_at = 0.0
                    # Comando direto só se a fala começou DEPOIS de abrir a janela de conversa
                    # e fora da fala do JARVIS (+ eco)
                    since = self._capture_since
                    is_command = since is not None and seg_start >= since - 0.2 \
                        and self._jarvis_text_at(seg_start) is None
                    woke = False
                continue

            seg.append(frame)
            seg_t = t
            if speech:
                speech_frames += 1
                silence_frames = 0
            else:
                silence_frames += 1
            dur = len(seg) * FRAME_S

            # Checagem contínua do wake word (inclui durante a fala do JARVIS => barge-in)
            # Durante a fala do JARVIS checa com mais frequência (a palavra não pode cair entre janelas)
            hop = cfg.wake_hop * 0.6 if self.speaking else cfg.wake_hop
            if not is_command and dur >= 1.0 and dur - checked_at >= hop:
                checked_at = dur
                window = np.concatenate(seg)[-int(cfg.wake_window * SR):]
                if self._check_wake(window, seg_t - cfg.wake_window / 2):
                    is_command = woke = True
                    if self.on_wake:
                        self._emit(self.on_wake)

            ended = silence_frames * FRAME_S >= cfg.end_silence or dur >= cfg.max_utterance
            if not ended:
                continue

            in_speech = False
            pre_roll.clear()
            if speech_frames * FRAME_S < cfg.min_speech:
                continue

            audio = np.concatenate(seg)
            # Frase curta ("Jarvis.") ou final ainda não checado
            if not is_command and (checked_at == 0.0 or dur - checked_at > 0.4):
                if checked_at:
                    chunk, chunk_t = audio[-int(cfg.wake_window * SR):], seg_t - cfg.wake_window / 2
                else:
                    chunk, chunk_t = audio[:int(cfg.wake_window * SR)], seg_start + 0.5
                if self._check_wake(chunk, chunk_t):
                    is_command = woke = True
                    if self.on_wake:
                        self._emit(self.on_wake)

            if is_command and self.commands is not None:
                if DEBUG:
                    print(f"[Listener] comando pronto: fala terminou há {time.monotonic() - seg_t:.2f}s "
                          f"(atraso de processamento), {dur:.1f}s de áudio")
                utt = Utterance(audio=audio, woke=woke, duration=dur)
                self._emit(self.commands.put_nowait, utt)
