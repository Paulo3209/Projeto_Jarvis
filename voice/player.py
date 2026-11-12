"""
Player de áudio interrompível + sons de interface.

`play()` retorna False se a reprodução foi interrompida (barge-in: o usuário
disse "Jarvis" enquanto o JARVIS falava).
"""
from __future__ import annotations

import asyncio
import time

import numpy as np
import sounddevice as sd


class AudioPlayer:
    def __init__(self):
        self._interrupted = False
        self.playing = False

    async def play(self, samples: np.ndarray, sr: int) -> bool:
        if samples is None or len(samples) == 0:
            return True
        self._interrupted = False
        self.playing = True
        try:
            sd.play(samples, sr)
            duration = len(samples) / sr
            start = time.monotonic()
            while time.monotonic() - start < duration + 0.05:
                if self._interrupted:
                    sd.stop()
                    return False
                await asyncio.sleep(0.02)
            return True
        finally:
            self.playing = False

    def stop(self) -> None:
        """Interrompe imediatamente (seguro chamar a qualquer momento)."""
        self._interrupted = True
        try:
            sd.stop()
        except Exception:
            pass


def _tone(freqs: list[float], dur: float, sr: int, volume: float) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    wave = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    env = np.minimum(1.0, np.minimum(t / 0.01, (dur - t) / 0.06))  # ataque/decay suaves
    return (wave * env * volume).astype(np.float32)


def chime(sr: int = 24000) -> np.ndarray:
    """'Bip' holográfico curto de ativação (duas notas ascendentes)."""
    return np.concatenate([
        _tone([880, 1320], 0.07, sr, 0.18),
        _tone([1175, 1760], 0.10, sr, 0.15),
    ])
