"""
Clap Detector - Detecta 2 palmas (double clap) para ativar JARVIS.
Baseado em RMS threshold + timing entre palmas.
Inspirado no jarvis-show da referência.
"""
from __future__ import annotations
import asyncio
import time
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

import numpy as np

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False


class ClapState(Enum):
    IDLE = "idle"
    FIRST_CLAP = "first_clap"
    SECOND_CLAP = "second_clap"
    TRIGGERED = "triggered"


@dataclass
class ClapConfig:
    """Configuração do detector de palmas."""
    sample_rate: int = 16000
    frame_duration_ms: int = 50
    rms_threshold: float = 0.08  # Ajuste conforme microfone/ambiente
    min_clap_interval: float = 0.15  # Min 150ms entre palmas
    max_clap_interval: float = 1.0   # Max 1s entre palmas
    cooldown_seconds: float = 2.0    # Cooldown após trigger
    microphone_index: Optional[int] = None  # None = default


class ClapDetector:
    """
    Detecta double-clap (2 palmas rápidas) em tempo real.
    Callback é chamado quando detecta o padrão.
    """

    def __init__(self, config: ClapConfig = None, on_double_clap: Callable = None):
        self.config = config or ClapConfig()
        self.on_double_clap = on_double_clap
        self.state = ClapState.IDLE
        self.first_clap_time: Optional[float] = None
        self.last_trigger_time: float = 0
        self._running = False
        self._stream = None
        self._audio_buffer = deque(maxlen=100)
        self._rms_history = deque(maxlen=200)

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback de áudio (thread do sounddevice)."""
        if status:
            print(f"[ClapDetector] Status: {status}")

        # Calcula RMS do frame
        audio = indata[:, 0] if indata.ndim > 1 else indata
        rms = np.sqrt(np.mean(audio**2))
        self._rms_history.append((time.time(), rms))

        # Verifica se passou do threshold
        if rms > self.config.rms_threshold:
            self._process_clap_candidate(rms)

    def _process_clap_candidate(self, rms: float):
        """Processa candidato a palma com debounce temporal."""
        now = time.time()

        # Evita múltiplas detecções no mesmo pico (debounce 100ms)
        recent = [t for t, r in self._rms_history if now - t < 0.1]
        if len(recent) > 3:  # Já detectou recentemente
            return

        if self.state == ClapState.IDLE:
            self.state = ClapState.FIRST_CLAP
            self.first_clap_time = now
            print(f"[ClapDetector] 👏 Primeira palma detectada (RMS: {rms:.4f})")

        elif self.state == ClapState.FIRST_CLAP:
            interval = now - self.first_clap_time
            if self.config.min_clap_interval <= interval <= self.config.max_clap_interval:
                # DOUBLE CLAP CONFIRMADO!
                self.state = ClapState.TRIGGERED
                self.last_trigger_time = now
                print(f"[ClapDetector] 🎉 DOUBLE CLAP! Intervalo: {interval:.3f}s")

                # Chama callback de forma assíncrona
                if self.on_double_clap:
                    asyncio.create_task(self._safe_callback())
            else:
                # Intervalo fora do range - reseta
                if interval > self.config.max_clap_interval:
                    print(f"[ClapDetector] ⏱️ Intervalo muito longo ({interval:.3f}s), resetando")
                self.state = ClapState.IDLE
                self.first_clap_time = None

        # Cooldown automático
        if now - self.last_trigger_time > self.config.cooldown_seconds:
            self.state = ClapState.IDLE
            self.first_clap_time = None

    async def _safe_callback(self):
        """Executa callback com tratamento de erro."""
        try:
            if asyncio.iscoroutinefunction(self.on_double_clap):
                await self.on_double_clap()
            else:
                self.on_double_clap()
        except Exception as e:
            print(f"[ClapDetector] Erro no callback: {e}")

    def start(self) -> bool:
        """Inicia detecção contínua."""
        if not SOUNDDEVICE_AVAILABLE:
            print("[ClapDetector] ❌ sounddevice não instalado")
            return False

        if self._running:
            return True

        try:
            self._running = True
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                blocksize=int(self.config.sample_rate * self.config.frame_duration_ms / 1000),
                channels=1,
                dtype='float32',
                callback=self._audio_callback,
                device=self.config.microphone_index
            )
            self._stream.start()
            print(f"[ClapDetector] ✅ Iniciado (threshold: {self.config.rms_threshold})")
            return True
        except Exception as e:
            print(f"[ClapDetector] ❌ Erro ao iniciar: {e}")
            self._running = False
            return False

    def stop(self):
        """Para detecção."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        print("[ClapDetector] 🛑 Parado")

    def set_threshold(self, threshold: float):
        """Ajusta threshold de RMS dinamicamente."""
        self.config.rms_threshold = max(0.01, min(0.5, threshold))
        print(f"[ClapDetector] Threshold ajustado para: {self.config.rms_threshold}")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "state": self.state.value,
            "threshold": self.config.rms_threshold,
            "sample_rate": self.config.sample_rate,
        }


# ==================== AUTO-CALIBRAÇÃO ====================

async def calibrate_clap_detector(detector: ClapDetector, duration: float = 10.0) -> float:
    """
    Calibra threshold automaticamente ouvindo ambiente.
    Retorna threshold sugerido.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return detector.config.rms_threshold

    print(f"[ClapDetector] 🔧 Calibrando por {duration}s... faça barulho normal (sem palmas)")

    rms_values = []
    calibration_done = asyncio.Event()

    def cal_callback(indata, frames, time_info, status):
        audio = indata[:, 0] if indata.ndim > 1 else indata
        rms = np.sqrt(np.mean(audio**2))
        rms_values.append(rms)

    stream = sd.InputStream(
        samplerate=detector.config.sample_rate,
        blocksize=int(detector.config.sample_rate * detector.config.frame_duration_ms / 1000),
        channels=1,
        dtype='float32',
        callback=cal_callback
    )
    stream.start()

    await asyncio.sleep(duration)
    stream.stop()
    stream.close()

    if rms_values:
        mean_rms = np.mean(rms_values)
        std_rms = np.std(rms_values)
        # Threshold = média + 3 desvios (99.7% de ruído normal abaixo)
        suggested = mean_rms + 3 * std_rms
        # Mínimo 0.05, máximo 0.3
        suggested = max(0.05, min(0.3, suggested))
        print(f"[ClapDetector] 📊 RMS médio: {mean_rms:.5f}, std: {std_rms:.5f}")
        print(f"[ClapDetector] 🎯 Threshold sugerido: {suggested:.4f}")
        return suggested

    return detector.config.rms_threshold


# ==================== FERRAMENTAS PARA O BRAIN ====================

from core.plugin_system import tool, ToolCategory


@tool(description="Inicia detector de palmas (2 palmas = ativa JARVIS).", category=ToolCategory.SYSTEM)
def clap_detector_start(threshold: float = 0.08, mic_index: int = None) -> dict:
    """Inicia detector. threshold 0.01-0.5 (padrão 0.08)."""
    global _clap_detector
    if '_clap_detector' not in globals():
        _clap_detector = ClapDetector(ClapConfig(rms_threshold=threshold, microphone_index=mic_index))

    def on_clap():
        # Emite evento para voice bridge ou main
        from core.event_bus import get_event_bus, EventType, StatusChangeEvent
        import asyncio
        asyncio.create_task(_emit_clap_event())

    async def _emit_clap_event():
        bus = await get_event_bus()
        bus.emit(StatusChangeEvent("clap_detected", source="clap_detector"))

    _clap_detector.on_double_clap = on_clap
    success = _clap_detector.start()
    return {"success": success, "threshold": threshold}


@tool(description="Para detector de palmas.", category=ToolCategory.SYSTEM)
def clap_detector_stop() -> dict:
    """Para o detector."""
    global _clap_detector
    if '_clap_detector' in globals() and _clap_detector:
        _clap_detector.stop()
        return {"success": True, "message": "Detector parado"}
    return {"success": False, "message": "Detector não iniciado"}


@tool(description="Calibra threshold do detector de palmas automaticamente.", category=ToolCategory.SYSTEM)
def clap_detector_calibrate(duration: float = 10.0) -> dict:
    """Ouve ambiente por N segundos e sugere threshold."""
    global _clap_detector
    if '_clap_detector' not in globals():
        _clap_detector = ClapDetector()

    async def _cal():
        suggested = await calibrate_clap_detector(_clap_detector, duration)
        _clap_detector.set_threshold(suggested)
        return {"success": True, "suggested_threshold": round(suggested, 4)}

    import asyncio
    return asyncio.run(_cal())


@tool(description="Mostra status do detector de palmas.", category=ToolCategory.SYSTEM)
def clap_detector_status() -> dict:
    """Status atual."""
    global _clap_detector
    if '_clap_detector' in globals() and _clap_detector:
        return {"success": True, **_clap_detector.get_status()}
    return {"success": False, "message": "Detector não inicializado"}


# Export
AVAILABLE_FUNCTIONS = {
    "clap_detector_start": clap_detector_start,
    "clap_detector_stop": clap_detector_stop,
    "clap_detector_calibrate": clap_detector_calibrate,
    "clap_detector_status": clap_detector_status,
}