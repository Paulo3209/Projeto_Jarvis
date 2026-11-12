"""
Voice Bridge - Connects TTS/STT to EventBus and Brain.
Handles voice events and integrates with async backend.
"""
from __future__ import annotations
import asyncio
from typing import Optional, Callable
from dataclasses import dataclass

from core.event_bus import (
    EventBus, EventType, get_event_bus,
    VoiceTranscriptionEvent, VoiceSpeakStartEvent, VoiceSpeakEndEvent,
    UserMessageEvent,
)

from voice.tts import EdgeTTS, VoiceConfig, VoiceType
from voice.stt import FasterWhisperSTT, STTConfig, ModelSize, ComputeType


@dataclass
class VoiceSettings:
    """Voice system settings."""
    # TTS
    tts_personality: str = "jarvis"  # "default", "minimal", "friendly", "jarvis"
    tts_voice: VoiceType = VoiceType.ANTONIO
    tts_rate: str = "-5%"
    tts_pitch: str = "-10Hz"

    # STT
    stt_model: ModelSize = ModelSize.BASE
    stt_compute_type: ComputeType = ComputeType.INT8
    stt_vad: bool = True
    wake_word: str = "jarvis"

    # Behavior
    auto_speak: bool = True          # Auto-speak assistant responses
    continuous_listening: bool = False  # Continuous listening mode
    push_to_talk: bool = True        # Require button press (HUD)


class VoiceBridge:
    """
    Bridges TTS/STT with EventBus and Brain.
    Subscribes to assistant responses for TTS, publishes transcriptions as user messages.
    """

    def __init__(self, settings: Optional[VoiceSettings] = None):
        self.settings = settings or VoiceSettings()
        self._event_bus: Optional[EventBus] = None
        self._tts: Optional[EdgeTTS] = None
        self._stt: Optional[FasterWhisperSTT] = None
        self._listening_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._speak_queue: asyncio.Queue = asyncio.Queue()
        self._speak_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize TTS, STT, and EventBus subscriptions."""
        if self._initialized:
            return

        self._event_bus = await get_event_bus()

        # Initialize TTS
        tts_config = VoiceConfig(
            voice=self.settings.tts_voice,
            rate=self.settings.tts_rate,
            pitch=self.settings.tts_pitch,
        )
        self._tts = EdgeTTS(config=tts_config, personality=self.settings.tts_personality)

        # Initialize STT
        stt_config = STTConfig(
            model_size=self.settings.stt_model,
            compute_type=self.settings.stt_compute_type,
            vad_filter=self.settings.stt_vad,
        )
        self._stt = FasterWhisperSTT(stt_config)
        # Load model in background
        asyncio.create_task(self._load_stt_model())

        # Subscribe to events
        await self._subscribe_events()

        # Start speak queue processor
        self._speak_task = asyncio.create_task(self._process_speak_queue())

        self._initialized = True
        print("[VoiceBridge] Inicializado")

    async def _load_stt_model(self) -> None:
        """Load STT model in background."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stt.load_model)
        print("[VoiceBridge] Modelo STT carregado")

    async def _subscribe_events(self) -> None:
        """Subscribe to relevant EventBus events."""
        if not self._event_bus:
            return

        # Assistant complete response -> TTS
        self._event_bus.subscribe_async(
            EventType.ASSISTANT_RESPONSE_COMPLETE,
            self._on_assistant_response
        )

        # Voice speak start/end events (for HUD sync)
        self._event_bus.subscribe_async(
            EventType.VOICE_SPEAK_START,
            self._on_voice_speak_start
        )
        self._event_bus.subscribe_async(
            EventType.VOICE_SPEAK_END,
            self._on_voice_speak_end
        )

        # Voice transcription event (from HUD push-to-talk)
        self._event_bus.subscribe_async(
            EventType.VOICE_TRANSCRIPTION,
            self._on_voice_transcription
        )

    # Event handlers
    async def _on_assistant_response(self, event) -> None:
        """Handle assistant response - queue for TTS if auto_speak enabled."""
        if self.settings.auto_speak and self._tts:
            text = event.data.get('full_response', '').strip()
            if text:
                await self._speak_queue.put(text)

    async def _on_voice_speak_start(self, event) -> None:
        """Handle voice speak start (HUD sync)."""
        # Could emit status change
        pass

    async def _on_voice_speak_end(self, event) -> None:
        """Handle voice speak end (HUD sync)."""
        pass

    async def _on_voice_transcription(self, event) -> None:
        """Handle voice transcription from HUD - inject as user message."""
        text = event.data.get('text', '').strip()
        if text and self._event_bus:
            # Emit as user message to trigger brain
            from core.event_bus import UserMessageEvent
            self._event_bus.emit(UserMessageEvent(text, source="voice"))

    # Speak queue processor
    async def _process_speak_queue(self) -> None:
        """Process queued TTS requests sequentially."""
        while True:
            try:
                text = await self._speak_queue.get()
                if self._tts:
                    await self._tts.speak(text, blocking=True)
                self._speak_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[VoiceBridge] Erro no TTS: {e}")

    # Public API
    async def speak(self, text: str, blocking: bool = False) -> None:
        """Queue text for TTS."""
        if not self._initialized:
            await self.initialize()
        if blocking:
            if self._tts:
                await self._tts.speak(text, blocking=True)
        else:
            await self._speak_queue.put(text)

    async def speak_stream(self, text: str) -> None:
        """Stream TTS (low latency)."""
        if not self._initialized:
            await self.initialize()
        if self._tts:
            await self._tts.speak_stream(text)

    def stop_speaking(self) -> None:
        """Stop current TTS playback."""
        if self._tts:
            self._tts.stop()
        # Clear queue
        while not self._speak_queue.empty():
            try:
                self._speak_queue.get_nowait()
                self._speak_queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def listen_once(self) -> Optional[str]:
        """One-shot voice recognition."""
        if not self._initialized:
            await self.initialize()
        if self._stt:
            return await self._stt.listen_once()
        return None

    async def start_continuous_listening(
        self,
        on_transcription: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Start continuous listening with wake word."""
        if not self._initialized:
            await self.initialize()

        if self._listening_task and not self._listening_task.done():
            return  # Already listening

        self._stt.set_wake_word(self.settings.wake_word)

        async def _on_wake():
            print("[VoiceBridge] Wake word detectado!")
            if self._event_bus:
                self._event_bus.emit(
                    VoiceSpeakStartEvent("Wake word detectado", source="voice")
                )

        async def _on_transcription(text: str):
            print(f"[VoiceBridge] Transcrição: {text}")
            if self._event_bus:
                self._event_bus.emit(UserMessageEvent(text, source="voice"))
            if on_transcription:
                await on_transcription(text)

        self._listening_task = asyncio.create_task(
            self._stt.listen_continuous(
                on_transcription=_on_transcription,
                on_wake_word=_on_wake,
            )
        )

    async def stop_continuous_listening(self) -> None:
        """Stop continuous listening."""
        if self._stt:
            self._stt.stop_listening()
        if self._listening_task:
            self._listening_task.cancel()
            try:
                await self._listening_task
            except asyncio.CancelledError:
                pass
            self._listening_task = None

    def set_voice(self, voice: VoiceType) -> None:
        """Change TTS voice."""
        if self._tts:
            self._tts.set_voice(voice)
        self.settings.tts_voice = voice

    def set_wake_word(self, wake_word: str) -> None:
        """Change wake word."""
        self.settings.wake_word = wake_word
        if self._stt:
            self._stt.set_wake_word(wake_word)

    def set_auto_speak(self, enabled: bool) -> None:
        """Enable/disable auto-speak for assistant responses."""
        self.settings.auto_speak = enabled

    async def shutdown(self) -> None:
        """Shutdown voice bridge."""
        self.stop_speaking()
        await self.stop_continuous_listening()
        if self._speak_task:
            self._speak_task.cancel()
            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass
        if self._tts:
            self._tts.stop()
        print("[VoiceBridge] Finalizado")


# Global instance
_voice_bridge: Optional[VoiceBridge] = None


async def get_voice_bridge(settings: Optional[VoiceSettings] = None) -> VoiceBridge:
    """Get or create global VoiceBridge instance."""
    global _voice_bridge
    if _voice_bridge is None:
        _voice_bridge = VoiceBridge(settings)
        await _voice_bridge.initialize()
    return _voice_bridge


async def speak(text: str, personality: str = "jarvis", blocking: bool = False) -> None:
    """Convenience function to speak text."""
    bridge = await get_voice_bridge()
    await bridge.speak(text, blocking=blocking)


if __name__ == "__main__":
    # Test
    async def test():
        bridge = await get_voice_bridge()
        print("Testing TTS...")
        await bridge.speak("Sistemas de voz online.", blocking=True)

        print("Testing STT (fale algo)...")
        text = await bridge.listen_once()
        print(f"Você disse: {text}")

    asyncio.run(test())