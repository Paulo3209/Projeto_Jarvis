"""
STT Module - Faster Whisper with VAD (Voice Activity Detection).
Supports continuous listening and wake word detection.
"""
from __future__ import annotations
import asyncio
import io
import tempfile
import os
import wave
from typing import Optional, AsyncGenerator, Callable
from dataclasses import dataclass
from enum import Enum
import threading
import queue
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel


class ModelSize(Enum):
    """Whisper model sizes (speed vs accuracy trade-off)."""
    TINY = "tiny"           # ~39 MB, fastest, least accurate
    BASE = "base"           # ~74 MB, fast, good accuracy
    SMALL = "small"         # ~244 MB, balanced
    MEDIUM = "medium"       # ~769 MB, slower, more accurate
    LARGE_V3 = "large-v3"   # ~1550 MB, slowest, most accurate


class ComputeType(Enum):
    """Compute types for CTranslate2."""
    FLOAT32 = "float32"     # CPU default
    FLOAT16 = "float16"     # GPU default
    INT8 = "int8"           # CPU quantized (fastest on CPU)
    INT8_FLOAT16 = "int8_float16"  # Mixed


@dataclass
class STTConfig:
    """STT configuration."""
    model_size: ModelSize = ModelSize.BASE
    compute_type: ComputeType = ComputeType.INT8
    device: str = "auto"       # "auto", "cpu", "cuda"
    language: str = "pt"       # Language code
    beam_size: int = 1          # 1 = greedy: ~2-3x mais rápido que 5 na CPU
    vad_filter: bool = True    # Voice Activity Detection
    vad_min_silence_duration: float = 0.5  # seconds (Silero VAD dentro do Whisper)
    vad_threshold: float = 0.5  # Silero VAD threshold (0-1) - NÃO é energia do microfone
    # Detecção de fala por energia (RMS) do microfone - escala bem diferente do VAD acima
    rms_threshold: float = 0.012        # Acima disso = alguém falando
    end_silence_seconds: float = 0.8    # Silêncio após a fala que encerra a frase
    max_utterance_seconds: float = 15.0
    initial_prompt: str = "Jarvis, abra o navegador. Jarvis, qual o status do sistema?"


class AudioRecorder:
    """Low-latency audio recorder with VAD."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = "float32",
        block_duration: float = 0.1,  # 100ms blocks
        vad_threshold: float = 0.01,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.block_duration = block_duration
        self.block_size = int(sample_rate * block_duration)
        self.vad_threshold = vad_threshold

        self._stream: Optional[sd.InputStream] = None
        self._recording = False
        self._audio_queue: queue.Queue = queue.Queue()
        self._callback_thread: Optional[threading.Thread] = None

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice callback - runs in audio thread."""
        if status:
            print(f"[AudioRecorder] Status: {status}")
        if self._recording:
            # Simple VAD: check RMS energy
            rms = np.sqrt(np.mean(indata**2))
            self._audio_queue.put((indata.copy(), rms))

    def start(self) -> None:
        """Start recording."""
        if self._recording:
            return

        self._recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.block_size,
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return accumulated audio."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Collect all audio from queue
        chunks = []
        while not self._audio_queue.empty():
            try:
                chunk, _ = self._audio_queue.get_nowait()
                chunks.append(chunk)
            except queue.Empty:
                break

        if chunks:
            return np.concatenate(chunks, axis=0)
        return np.array([], dtype=self.dtype)

    def get_audio_chunks(self) -> AsyncGenerator[np.ndarray, None]:
        """Async generator yielding audio chunks with VAD info."""
        while self._recording:
            try:
                chunk, rms = self._audio_queue.get(timeout=0.1)
                yield chunk, rms
            except queue.Empty:
                continue


class FasterWhisperSTT:
    """Faster Whisper STT with continuous listening support."""

    def __init__(self, config: Optional[STTConfig] = None):
        self.config = config or STTConfig()
        self._model: Optional[WhisperModel] = None
        self._recorder: Optional[AudioRecorder] = None
        self._listening = False
        self._abort = False
        self._wake_word = "jarvis"
        self._wake_word_callback: Optional[Callable] = None

    def load_model(self) -> None:
        """Load the Whisper model (blocking, run once)."""
        if self._model is None:
            print(f"[STT] Carregando modelo {self.config.model_size.value}...")
            self._model = WhisperModel(
                self.config.model_size.value,
                device=self.config.device,
                compute_type=self.config.compute_type.value,
                cpu_threads=max(4, (os.cpu_count() or 8) // 2),  # usa todos os núcleos físicos
            )
            # Aquece: a 1ª inferência do CTranslate2 é bem mais lenta
            list(self._model.transcribe(np.zeros(16000, np.float32), language=self.config.language)[0])
            print("[STT] Modelo carregado!")

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert numpy audio to WAV bytes."""
        # Normalize to int16
        audio_int16 = (audio * 32767).astype(np.int16)

        with io.BytesIO() as wav_io:
            with wave.open(wav_io, 'wb') as wav_file:
                wav_file.setnchannels(self.config.channels if hasattr(self.config, 'channels') else 1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(16000)
                wav_file.writeframes(audio_int16.tobytes())
            return wav_io.getvalue()

    async def transcribe_audio(self, audio: np.ndarray) -> str:
        """Transcribe audio array to text."""
        if self._model is None:
            self.load_model()

        # Run in executor to not block event loop
        loop = asyncio.get_event_loop()

        def _transcribe():
            # Passa o array direto (16 kHz float32): evita gravar WAV e decodificar
            # com PyAV, que quebra em algumas versões ("metadata_errors").
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            segments, info = self._model.transcribe(
                samples,
                language=self.config.language,
                beam_size=self.config.beam_size,
                initial_prompt=self.config.initial_prompt or None,
                condition_on_previous_text=False,
                without_timestamps=True,
                vad_filter=self.config.vad_filter,
                vad_parameters=dict(
                    min_silence_duration_ms=int(self.config.vad_min_silence_duration * 1000),
                    threshold=self.config.vad_threshold,
                ) if self.config.vad_filter else None,
            )
            return " ".join(seg.text for seg in segments).strip()

        return await loop.run_in_executor(None, _transcribe)

    async def transcribe_stream(
        self,
        audio_chunks: AsyncGenerator[np.ndarray, None]
    ) -> AsyncGenerator[str, None]:
        """Stream transcription from audio chunks (not fully implemented - faster-whisper needs full audio)."""
        # Note: faster-whisper works best with complete audio segments
        # For true streaming, consider using whisper.cpp with streaming support
        pass

    def set_wake_word(self, wake_word: str, callback: Optional[Callable] = None) -> None:
        """Set wake word for activation."""
        self._wake_word = wake_word.lower()
        self._wake_word_callback = callback

    async def listen_once(self, timeout: float = 10.0) -> Optional[str]:
        """Escuta uma frase completa.

        Espera até `timeout` segundos pelo INÍCIO da fala; depois grava até
        detectar `end_silence_seconds` de silêncio (ou `max_utterance_seconds`).
        Retorna None se ninguém falou (não gasta CPU transcrevendo silêncio).
        """
        self._recorder = AudioRecorder(vad_threshold=self.config.rms_threshold)
        self._recorder.start()
        recorder = self._recorder
        block = recorder.block_duration

        start_time = time.time()
        pre_roll: list = []           # ~0.5s antes da fala, para não cortar a 1ª sílaba
        audio_chunks: list = []
        speech_started = False
        speech_time = 0.0
        silence_duration = 0.0

        try:
            self._abort = False
            while not self._abort:
                try:
                    chunk, rms = recorder._audio_queue.get_nowait()
                except queue.Empty:
                    if not speech_started and time.time() - start_time > timeout:
                        break
                    await asyncio.sleep(0.03)  # libera o event loop
                    continue

                if not speech_started:
                    pre_roll.append(chunk)
                    pre_roll = pre_roll[-5:]
                    if rms >= self.config.rms_threshold:
                        speech_started = True
                        audio_chunks.extend(pre_roll)
                    elif time.time() - start_time > timeout:
                        break
                    continue

                audio_chunks.append(chunk)
                if rms < self.config.rms_threshold:
                    silence_duration += block
                else:
                    silence_duration = 0.0
                    speech_time += block

                total = len(audio_chunks) * block
                if silence_duration >= self.config.end_silence_seconds or total >= self.config.max_utterance_seconds:
                    break

            recorder.stop()
            # Ruído curto (clique, tosse) não vale transcrição
            if not speech_started or speech_time < 0.25:
                return None

            audio = np.concatenate(audio_chunks, axis=0)
            text = await self.transcribe_audio(audio)
            return text.strip() if text and text.strip() else None

        except Exception as e:
            print(f"[STT] Erro: {e}")
            recorder.stop()
            return None

    async def listen_continuous(
        self,
        on_transcription: Callable[[str], None],
        on_wake_word: Optional[Callable] = None,
    ) -> None:
        """Continuous listening with wake word detection."""
        self._listening = True
        self._recorder = AudioRecorder(vad_threshold=self.config.vad_threshold)
        self._recorder.start()

        print(f"[STT] Escuta contínua iniciada. Wake word: '{self._wake_word}'")
        awake_until = 0.0            # janela de conversa após o wake word
        conversation_window = 8.0

        try:
            while self._listening:
                text = await self.listen_once(timeout=30.0)
                if not text:
                    continue

                print(f"[STT] Transcrito: {text}")
                if time.time() > awake_until:
                    found, remainder = detect_wake_word(text, self._wake_word)
                    if not found:
                        continue  # Ignora até ouvir o wake word
                    print("[STT] Wake word detectado!")
                    if on_wake_word:
                        await on_wake_word()
                    awake_until = time.time() + conversation_window
                    text = remainder
                    if not text:
                        continue

                if on_transcription:
                    await on_transcription(text)
                awake_until = time.time() + conversation_window

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[STT] Erro na escuta contínua: {e}")
        finally:
            self.stop_listening()

    def stop_listening(self) -> None:
        """Stop continuous listening."""
        self._listening = False
        self._abort = True
        if self._recorder:
            self._recorder.stop()
            self._recorder = None
        print("[STT] Escuta parada.")


# ==================== Wake word ====================
import re as _re
import unicodedata as _ud

# Como o Whisper costuma transcrever "Jarvis" em pt-BR
WAKE_VARIANTS = ("jarvis", "jarvys", "jarves", "jarviz", "jarbas", "javis", "djarvis", "jarvi", "jervis", "charvis")


def _normalize(text: str) -> str:
    text = _ud.normalize("NFD", text.lower())
    return "".join(c for c in text if _ud.category(c) != "Mn")


def detect_wake_word(text: str, wake_word: str = "jarvis") -> tuple[bool, str]:
    """Detecta o wake word (tolerante a erros do Whisper) e retorna o restante da frase.

    Ex.: "Jarbas, abra o Chrome." -> (True, "abra o Chrome")
    """
    target = _normalize(wake_word)
    variants = set(WAKE_VARIANTS) | {target} if target == "jarvis" else {target}
    words = text.split()
    for i, word in enumerate(words):
        if _normalize(word).strip(",.!?:;-\"'") in variants:
            rest = words[:i] + words[i + 1:]
            # Descarta interjeições antes do nome ("ok jarvis", "ei jarvis")
            if i > 0 and all(_normalize(w).strip(",.!?") in {"ok", "ei", "hey", "e", "oi", "ola"} for w in words[:i]):
                rest = words[i + 1:]
            return True, " ".join(rest).strip(" ,.!?;:-")
    return False, text


def wake_in_text(text: str, wake_word: str = "jarvis", fuzzy: bool = True) -> bool:
    """True se o texto contém o wake word. Com `fuzzy`, aceita transcrições
    aproximadas do Whisper tiny ("Já é visto", "jaevis", "jarvi")."""
    if detect_wake_word(text, wake_word)[0]:
        return True
    if not fuzzy:
        return False
    import difflib
    target = _normalize(wake_word)
    words = [_re.sub(r"[^a-z]", "", _normalize(w)) for w in text.split()[:5]]
    words = [w for w in words if w]
    # Junta até 3 palavras vizinhas ("ja e visto" -> "jaevisto") e compara prefixos
    for i in range(len(words)):
        joined = ""
        for w in words[i:i + 3]:
            joined += w
            for n in range(len(target) - 1, len(target) + 2):
                cand = joined[:n]
                if len(cand) >= len(target) - 1 and cand[0] in "jgc" and \
                        ("rv" in cand or "ev" in cand) and \
                        not any(x.startswith(("revis", "previs", "ervil")) for x in words[i + 1:i + 3]) and \
                        difflib.SequenceMatcher(None, cand, target).ratio() >= 0.8:
                    return True
    return False

# Convenience functions
async def transcribe_once(
    text_callback: Optional[Callable[[str], None]] = None,
    model_size: ModelSize = ModelSize.BASE,
) -> Optional[str]:
    """Quick one-shot transcription."""
    stt = FasterWhisperSTT(STTConfig(model_size=model_size))
    stt.load_model()
    result = await stt.listen_once()
    if result and text_callback:
        await text_callback(result)
    return result


if __name__ == "__main__":
    # Test
    async def test():
        stt = FasterWhisperSTT(STTConfig(model_size=ModelSize.TINY))
        stt.load_model()
        print("Fale algo...")
        text = await stt.listen_once()
        print(f"Você disse: {text}")

    asyncio.run(test())