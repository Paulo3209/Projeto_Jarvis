"""
TTS Híbrido: Kokoro (local, offline) primário + edge-tts (cloud) fallback.
Kokoro suporta pt-BR nativamente com voz 'pf_dora'.
"""
from __future__ import annotations
import asyncio
import os
import tempfile
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, AsyncGenerator

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class TTSProvider(Enum):
    KOKORO = "kokoro"
    EDGE_TTS = "edge_tts"


@dataclass
class TTSConfig:
    """Configuração TTS híbrido."""
    primary: TTSProvider = TTSProvider.KOKORO
    kokoro_model_path: str = ""  # Auto-detect ou caminho explícito
    kokoro_voice: str = "pm_alex"  # pt-BR masculina (estilo JARVIS)
    kokoro_speed: float = 0.95
    edge_voice: str = "pt-BR-AntonioNeural"  # Fallback (masculina, grave)
    edge_rate: str = "-4%"
    edge_pitch: str = "-8Hz"
    fallback_on_error: bool = True
    sample_rate: int = 24000


class BaseTTS(ABC):
    """Interface comum para TTS."""

    @abstractmethod
    async def speak(self, text: str, blocking: bool = True) -> bool:
        """Fala o texto. Retorna True se sucesso."""
        pass

    @abstractmethod
    async def speak_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream de áudio (para baixa latência)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def stop(self):
        pass


class KokoroTTS(BaseTTS):
    """Kokoro TTS local (offline)."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self._model = None
        self._voicepack = None
        self._initialized = False
        self._use_onnx = True

    async def _ensure_model(self):
        """Carrega modelo Kokoro sob demanda."""
        if self._initialized:
            return

        try:
            # Tenta importar kokoro-onnx (versão ONNX mais rápida)
            from kokoro_onnx import Kokoro
            self._use_onnx = True
        except ImportError:
            try:
                # Fallback: kokoro original (PyTorch)
                from kokoro import KPipeline
                self._use_onnx = False
            except ImportError:
                raise RuntimeError(
                    "Kokoro não instalado. pip install kokoro-onnx ou kokoro"
                )

        # Determina caminho do modelo
        if self.config.kokoro_model_path:
            model_path = self.config.kokoro_model_path
        else:
            # Auto-detect: ~/.cache/kokoro ou pasta do projeto
            cache_dirs = [
                Path.home() / ".cache" / "kokoro",
                Path(__file__).resolve().parents[1] / "models" / "kokoro",
            ]
            model_path = None
            for d in cache_dirs:
                if (d / "kokoro-v1.0.onnx").exists():
                    model_path = str(d)
                    break
                if (d / "kokoro-v1.0.pth").exists():
                    model_path = str(d)
                    break

        if not model_path:
            raise RuntimeError(
                "Modelo Kokoro não encontrado. Baixe de: "
                "https://github.com/thewh1teagle/kokoro-onnx/releases"
            )

        if self._use_onnx:
            self._model = Kokoro(
                model_path=f"{model_path}/kokoro-v1.0.onnx",
                voices_path=f"{model_path}/voices-v1.0.bin"
            )
        else:
            self._model = KPipeline(lang_code='p', model_path=f"{model_path}/kokoro-v1.0.pth")

        self._initialized = True

    async def speak(self, text: str, blocking: bool = True) -> bool:
        await self._ensure_model()

        try:
            if self._use_onnx:
                # kokoro-onnx gera direto para arquivo
                import soundfile as sf
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                samples, sr = self._model.create(
                    text,
                    voice=self.config.kokoro_voice,
                    speed=self.config.kokoro_speed,
                    lang="pt-br"
                )
                sf.write(tmp_path, samples, sr)

                # Toca com sounddevice
                import sounddevice as sd
                sd.play(samples, sr)
                if blocking:
                    await asyncio.get_running_loop().run_in_executor(None, sd.wait)

                os.unlink(tmp_path)
            else:
                # kokoro original (generator)
                import sounddevice as sd
                import numpy as np

                generator = self._model(text, voice=self.config.kokoro_voice, speed=self.config.kokoro_speed)
                all_audio = []
                for _, _, audio in generator:
                    all_audio.append(audio)

                if all_audio:
                    combined = np.concatenate(all_audio)
                    sd.play(combined, self.config.sample_rate)
                    if blocking:
                        await asyncio.get_running_loop().run_in_executor(None, sd.wait)

            return True
        except Exception as e:
            raise RuntimeError(f"Kokoro: {e}") from e

    async def speak_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream não implementado para Kokoro (usa speak bloqueante)."""
        success = await self.speak(text, blocking=False)
        if success:
            yield b""  # Placeholder
        return

    def is_available(self) -> bool:
        try:
            from kokoro_onnx import Kokoro
            return True
        except ImportError:
            try:
                from kokoro import KPipeline
                return TORCH_AVAILABLE
            except ImportError:
                return False

    def stop(self):
        try:
            import sounddevice as sd
            sd.stop()
        except:
            pass


class EdgeTTS(BaseTTS):
    """edge-tts cloud fallback."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self._process = None

    async def speak(self, text: str, blocking: bool = True) -> bool:
        if not EDGE_TTS_AVAILABLE:
            return False

        try:
            communicate = edge_tts.Communicate(
                text,
                voice=self.config.edge_voice,
                rate=self.config.edge_rate,
                pitch=self.config.edge_pitch
            )

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name

            await communicate.save(tmp_path)

            # Toca com sounddevice
            import sounddevice as sd
            import soundfile as sf
            data, sr = sf.read(tmp_path)
            sd.play(data, sr)
            if blocking:
                await asyncio.get_running_loop().run_in_executor(None, sd.wait)

            os.unlink(tmp_path)
            return True
        except Exception as e:
            raise RuntimeError(f"edge-tts: {e}") from e

    async def speak_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not EDGE_TTS_AVAILABLE:
            return

        try:
            communicate = edge_tts.Communicate(
                text,
                voice=self.config.edge_voice,
                rate=self.config.edge_rate,
                pitch=self.config.edge_pitch
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            print(f"[EdgeTTS] Stream error: {e}")

    def is_available(self) -> bool:
        return EDGE_TTS_AVAILABLE

    def stop(self):
        try:
            import sounddevice as sd
            sd.stop()
        except:
            pass


class HybridTTS:
    """Orquestrador TTS Híbrido."""

    def __init__(self, config: TTSConfig = None):
        self.config = config or TTSConfig()
        self.kokoro = KokoroTTS(self.config)
        self.edge_tts = EdgeTTS(self.config)
        self.current_provider: Optional[TTSProvider] = None

    async def initialize(self):
        """Verifica provedores disponíveis."""
        kokoro_ok = self.kokoro.is_available()
        edge_ok = self.edge_tts.is_available()
        print(f"[HybridTTS] Kokoro: {'[OK]' if kokoro_ok else '[ERRO]'} | edge-tts: {'[OK]' if edge_ok else '[ERRO]'}")

        if self.config.primary == TTSProvider.KOKORO and kokoro_ok:
            self.current_provider = TTSProvider.KOKORO
        elif edge_ok:
            self.current_provider = TTSProvider.EDGE_TTS
        else:
            print("[HybridTTS] [AVISO]  Nenhum TTS disponível!")

    def _get_provider(self) -> BaseTTS:
        if self.current_provider == TTSProvider.KOKORO:
            return self.kokoro
        return self.edge_tts

    async def _maybe_fallback(self, error: Exception) -> Optional[BaseTTS]:
        if not self.config.fallback_on_error:
            return None

        if self.current_provider == TTSProvider.KOKORO:
            print(f"[HybridTTS] Kokoro falhou ({error}), tentando edge-tts...")
            if self.edge_tts.is_available():
                self.current_provider = TTSProvider.EDGE_TTS
                return self.edge_tts
        else:
            print(f"[HybridTTS] edge-tts falhou ({error}), tentando Kokoro...")
            if self.kokoro.is_available():
                self.current_provider = TTSProvider.KOKORO
                return self.kokoro
        return None

    async def speak(self, text: str, blocking: bool = True) -> bool:
        for attempt in range(2):
            provider = self._get_provider()
            if provider is None:
                return False
            try:
                if await provider.speak(text, blocking):
                    return True
                raise RuntimeError("provedor indisponível")
            except Exception as e:
                if attempt == 0:
                    fallback = await self._maybe_fallback(e)
                    if fallback:
                        continue
                print(f"[HybridTTS] Erro final: {e}")
                return False
        return False

    async def speak_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        provider = self._get_provider()
        if provider:
            async for chunk in provider.speak_stream(text):
                yield chunk

    def stop(self):
        self.kokoro.stop()
        self.edge_tts.stop()

    def get_status(self) -> dict:
        return {
            "current_provider": self.current_provider.value if self.current_provider else None,
            "kokoro_available": self.kokoro.is_available(),
            "edge_tts_available": self.edge_tts.is_available(),
        }


# Instância global
_hybrid_tts: Optional[HybridTTS] = None


async def get_hybrid_tts(config: TTSConfig = None) -> HybridTTS:
    global _hybrid_tts
    if _hybrid_tts is None:
        _hybrid_tts = HybridTTS(config)
        await _hybrid_tts.initialize()
    return _hybrid_tts