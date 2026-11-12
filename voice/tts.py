"""
TTS Module - Edge TTS with PT-BR neural voices.
Supports streaming playback and voice selection.
"""
from __future__ import annotations
import asyncio
import io
import tempfile
import os
from typing import Optional, AsyncGenerator
from dataclasses import dataclass
from enum import Enum

import edge_tts
import sounddevice as sd
import soundfile as sf
import numpy as np


class VoiceType(Enum):
    """Available Portuguese (Brazil) voices."""
    # Female voices
    FRANCISCA = "pt-BR-FranciscaNeural"      # Natural, expressive
    LETICIA = "pt-BR-LeticiaNeural"          # Clear, professional
    ANA = "pt-BR-AnaNeural"                  # Warm, friendly

    # Male voices
    ANTONIO = "pt-BR-AntonioNeural"          # Deep, authoritative
    DANIEL = "pt-BR-DanielNeural"            # Natural, conversational
    THIAGO = "pt-BR-ThiagoNeural"            # Young, energetic


@dataclass
class VoiceConfig:
    """TTS voice configuration."""
    voice: VoiceType = VoiceType.FRANCISCA
    rate: str = "+0%"          # Speech rate: -50% to +100%
    volume: str = "+0%"        # Volume: -50% to +100%
    pitch: str = "+0Hz"        # Pitch: -50Hz to +50Hz

    def to_edge_tts_args(self) -> dict:
        return {
            "voice": self.voice.value,
            "rate": self.rate,
            "volume": self.volume,
            "pitch": self.pitch,
        }


class EdgeTTS:
    """Edge TTS wrapper with streaming playback."""

    # Default voice configs for different personalities
    DEFAULT_CONFIGS = {
        "default": VoiceConfig(voice=VoiceType.FRANCISCA, rate="+0%", pitch="+0Hz"),
        "minimal": VoiceConfig(voice=VoiceType.LETICIA, rate="+10%", pitch="-5Hz"),
        "friendly": VoiceConfig(voice=VoiceType.ANA, rate="+5%", pitch="+5Hz"),
        "jarvis": VoiceConfig(voice=VoiceType.ANTONIO, rate="-5%", pitch="-10Hz"),
    }

    def __init__(self, config: Optional[VoiceConfig] = None, personality: str = "default"):
        self.config = config or self.DEFAULT_CONFIGS.get(personality, self.DEFAULT_CONFIGS["default"])
        self._stream: Optional[sd.OutputStream] = None
        self._playing = False
        self._sample_rate = 24000  # Edge TTS default

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (MP3)."""
        communicate = edge_tts.Communicate(text, **self.config.to_edge_tts_args())
        audio_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
        return bytes(audio_data)

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream audio chunks as they're generated."""
        communicate = edge_tts.Communicate(text, **self.config.to_edge_tts_args())
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    def _mp3_to_pcm(self, mp3_data: bytes) -> np.ndarray:
        """Convert MP3 bytes to PCM numpy array."""
        with io.BytesIO(mp3_data) as mp3_io:
            data, samplerate = sf.read(mp3_io)
            # Resample if needed
            if samplerate != self._sample_rate:
                import scipy.signal
                data = scipy.signal.resample(
                    data,
                    int(len(data) * self._sample_rate / samplerate)
                )
        return data.astype(np.float32)

    async def speak(self, text: str, blocking: bool = True) -> None:
        """Synthesize and play text."""
        if not text.strip():
            return

        mp3_data = await self.synthesize(text)
        pcm_data = self._mp3_to_pcm(mp3_data)

        if blocking:
            await self._play_pcm(pcm_data)
        else:
            asyncio.create_task(self._play_pcm(pcm_data))

    async def speak_stream(self, text: str) -> None:
        """Stream synthesis and playback simultaneously (low latency)."""
        if not text.strip():
            return

        # Create output stream
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=1024,
        )
        self._stream.start()
        self._playing = True

        try:
            async for chunk in self.synthesize_stream(text):
                if not self._playing:
                    break
                pcm_chunk = self._mp3_to_pcm(chunk)
                if len(pcm_chunk) > 0:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._stream.write,
                        pcm_chunk
                    )
        finally:
            self._playing = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    async def _play_pcm(self, pcm_data: np.ndarray) -> None:
        """Play PCM audio data."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sd.play, pcm_data, self._sample_rate)
        await loop.run_in_executor(None, sd.wait)

    def stop(self) -> None:
        """Stop current playback."""
        self._playing = False
        sd.stop()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def set_voice(self, voice: VoiceType) -> None:
        """Change voice."""
        self.config.voice = voice

    def set_config(self, config: VoiceConfig) -> None:
        """Update voice config."""
        self.config = config

    @classmethod
    def get_available_voices(cls) -> list[VoiceType]:
        """Get list of available PT-BR voices."""
        return list(VoiceType)


# Convenience function
async def speak(text: str, personality: str = "default", blocking: bool = True) -> None:
    """Quick speak function."""
    tts = EdgeTTS(personality=personality)
    await tts.speak(text, blocking=blocking)


if __name__ == "__main__":
    # Test
    async def test():
        tts = EdgeTTS(personality="jarvis")
        print("Testing JARVIS voice...")
        await tts.speak("Sistemas online. JARVIS à disposição.", blocking=True)
        print("Done!")

    asyncio.run(test())