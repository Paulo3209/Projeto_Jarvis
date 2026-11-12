"""
GUI Bridge - Connects PyQt6 HUD to async EventBus, Brain, and Voice.
Handles async/Qt event loop integration.
"""
from __future__ import annotations
import asyncio
import sys
import threading
from typing import Optional, Callable
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from core.event_bus import (
    EventBus, EventType, get_event_bus,
    UserMessageEvent, AssistantTokenEvent, AssistantResponseCompleteEvent,
    ToolCalledEvent, ToolCompletedEvent, ToolFailedEvent,
    MemorySavedEvent, MemoryRecalledEvent, ErrorEvent, StatusChangeEvent,
    VoiceTranscriptionEvent, VoiceSpeakStartEvent, VoiceSpeakEndEvent,
    VoiceStartListeningEvent, VoiceStopListeningEvent,
)
from gui.hud import HUDWindow

# Voice bridge (optional import)
try:
    from voice.bridge import VoiceBridge, VoiceSettings, get_voice_bridge
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    VoiceBridge = None
    VoiceSettings = None
    get_voice_bridge = None


class AsyncEventLoop(QObject):
    """Manages asyncio event loop in a separate thread."""

    # Signals to communicate with Qt main thread
    log_activity = pyqtSignal(str, str)  # message, type
    update_status = pyqtSignal(str, str)  # status, color
    append_token = pyqtSignal(str)  # streaming token
    log_user_msg = pyqtSignal(str)
    log_assistant_response = pyqtSignal(str)
    log_tool_call = pyqtSignal(str, dict)
    log_tool_result = pyqtSignal(str, bool, str)
    log_memory = pyqtSignal(str, str)
    log_error = pyqtSignal(str)
    set_input_enabled = pyqtSignal(bool)
    voice_status = pyqtSignal(str, str)  # status, color

    def __init__(self):
        super().__init__()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start the async event loop in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Wait for loop to be ready
        while self._loop is None and self._running:
            QTimer.singleShot(10, lambda: None)
            QApplication.processEvents()

    def _run_loop(self):
        """Run the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self):
        """Stop the async event loop."""
        if self._loop and self._running:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def run_coro(self, coro) -> asyncio.Future:
        """Run a coroutine in the async loop and return a Future."""
        if not self._loop:
            raise RuntimeError("Event loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run_sync(self, coro):
        """Run a coroutine and wait for result (blocking)."""
        future = self.run_coro(coro)
        return future.result()


class GUIBridge(QObject):
    """
    Bridges the PyQt6 HUD with the async EventBus, Brain, and Voice.
    Subscribes to EventBus events and forwards to HUD via Qt signals.
    """

    def __init__(self, hud: HUDWindow):
        super().__init__()
        self.hud = hud
        self.async_loop = AsyncEventLoop()
        self._event_bus: Optional[EventBus] = None
        self._voice_bridge: Optional[VoiceBridge] = None
        self._subscribed = False

        # Connect async loop signals to HUD slots
        self._connect_signals()

    def _connect_signals(self):
        """Connect async loop signals to HUD methods."""
        self.async_loop.log_activity.connect(self.hud.log_activity)
        self.async_loop.update_status.connect(self.hud.set_status)
        self.async_loop.append_token.connect(self.hud.append_streaming_token)
        self.async_loop.log_user_msg.connect(self.hud.log_user_message)
        self.async_loop.log_assistant_response.connect(self.hud.log_assistant_response)
        self.async_loop.log_tool_call.connect(self.hud.log_tool_call)
        self.async_loop.log_tool_result.connect(self.hud.log_tool_result)
        self.async_loop.log_memory.connect(self.hud.log_memory)
        self.async_loop.log_error.connect(self.hud.log_error)
        self.async_loop.set_input_enabled.connect(self.hud.set_input_enabled)
        self.async_loop.voice_status.connect(self.hud.set_status)

    async def initialize(self, enable_voice: bool = True):
        """Initialize event bus subscriptions and voice bridge."""
        self._event_bus = await get_event_bus()
        await self._subscribe_events()
        self._subscribed = True

        # Initialize voice bridge if available and enabled
        if enable_voice and VOICE_AVAILABLE:
            try:
                self._voice_bridge = await get_voice_bridge()
                # Subscribe to voice events
                await self._subscribe_voice_events()
                print("[GUIBridge] Voice bridge inicializado")
            except Exception as e:
                print(f"[GUIBridge] Erro ao inicializar voice: {e}")

    async def _subscribe_events(self):
        """Subscribe to all relevant EventBus events."""
        if not self._event_bus:
            return

        # User messages
        self._event_bus.subscribe_async(
            EventType.USER_MESSAGE,
            self._on_user_message
        )

        # Assistant streaming tokens
        self._event_bus.subscribe_async(
            EventType.ASSISTANT_TOKEN,
            self._on_assistant_token
        )

        # Assistant complete response
        self._event_bus.subscribe_async(
            EventType.ASSISTANT_RESPONSE_COMPLETE,
            self._on_assistant_response_complete
        )

        # Tool events
        self._event_bus.subscribe_async(
            EventType.TOOL_CALLED,
            self._on_tool_called
        )
        self._event_bus.subscribe_async(
            EventType.TOOL_COMPLETED,
            self._on_tool_completed
        )
        self._event_bus.subscribe_async(
            EventType.TOOL_FAILED,
            self._on_tool_failed
        )

        # Memory events
        self._event_bus.subscribe_async(
            EventType.MEMORY_SAVED,
            self._on_memory_saved
        )
        self._event_bus.subscribe_async(
            EventType.MEMORY_RECALLED,
            self._on_memory_recalled
        )

        # System events
        self._event_bus.subscribe_async(
            EventType.ERROR,
            self._on_error
        )
        self._event_bus.subscribe_async(
            EventType.STATUS_CHANGE,
            self._on_status_change
        )

    async def _subscribe_voice_events(self):
        """Subscribe to voice-specific events."""
        if not self._event_bus:
            return

        # Voice events
        self._event_bus.subscribe_async(
            EventType.VOICE_TRANSCRIPTION,
            self._on_voice_transcription
        )
        self._event_bus.subscribe_async(
            EventType.VOICE_SPEAK_START,
            self._on_voice_speak_start
        )
        self._event_bus.subscribe_async(
            EventType.VOICE_SPEAK_END,
            self._on_voice_speak_end
        )
        self._event_bus.subscribe_async(
            EventType.VOICE_START_LISTENING,
            self._on_voice_start_listening
        )
        self._event_bus.subscribe_async(
            EventType.VOICE_STOP_LISTENING,
            self._on_voice_stop_listening
        )

    # Event handlers - emit Qt signals for thread-safe UI updates
    async def _on_user_message(self, event: UserMessageEvent):
        self.async_loop.log_user_msg.emit(event.data['message'])

    async def _on_assistant_token(self, event: AssistantTokenEvent):
        self.async_loop.append_token.emit(event.data['token'])

    async def _on_assistant_response_complete(self, event: AssistantResponseCompleteEvent):
        self.async_loop.log_assistant_response.emit(event.data['full_response'])

    async def _on_tool_called(self, event: ToolCalledEvent):
        self.async_loop.log_tool_call.emit(event.data['name'], event.data['arguments'])

    async def _on_tool_completed(self, event: ToolCompletedEvent):
        result = event.data['result']
        self.async_loop.log_tool_result.emit(
            event.data['name'],
            result.get('success', False),
            result.get('message', '')
        )

    async def _on_tool_failed(self, event: ToolFailedEvent):
        self.async_loop.log_tool_result.emit(
            event.data['name'],
            False,
            event.data['error']
        )

    async def _on_memory_saved(self, event: MemorySavedEvent):
        self.async_loop.log_memory.emit('saved', event.data['content'])

    async def _on_memory_recalled(self, event: MemoryRecalledEvent):
        self.async_loop.log_memory.emit('recalled', f"query='{event.data['query']}', found={len(event.data['memories'])}")

    async def _on_error(self, event: ErrorEvent):
        self.async_loop.log_error.emit(event.data['error'])

    async def _on_status_change(self, event: StatusChangeEvent):
        status = event.data['status']
        color_map = {
            'online': '#00ff88',
            'processing': '#ffaa00',
            'shutdown': '#ff4444',
            'interrupted': '#ff4444',
        }
        color = color_map.get(status, '#00ffff')
        self.async_loop.update_status.emit(status, color)

    # Voice event handlers
    async def _on_voice_transcription(self, event: VoiceTranscriptionEvent):
        text = event.data.get('text', '')
        if text:
            self.async_loop.log_user_msg.emit(text)
            self.async_loop.log_activity.emit(f"🎤 {text}", 'user')

    async def _on_voice_speak_start(self, event: VoiceSpeakStartEvent):
        self.async_loop.voice_status.emit("SPEAKING", "#ffaa00")
        self.async_loop.log_activity.emit("🔊 JARVIS falando...", 'system')

    async def _on_voice_speak_end(self, event: VoiceSpeakEndEvent):
        self.async_loop.voice_status.emit("ONLINE", "#00ff88")
        self.async_loop.log_activity.emit("🔇 Fala finalizada", 'system')

    async def _on_voice_start_listening(self, event: VoiceStartListeningEvent):
        self.async_loop.voice_status.emit("LISTENING", "#00aaff")
        self.async_loop.log_activity.emit("🎧 Ouvindo...", 'system')

    async def _on_voice_stop_listening(self, event: VoiceStopListeningEvent):
        self.async_loop.voice_status.emit("ONLINE", "#00ff88")
        self.async_loop.log_activity.emit("🎧 Escuta finalizada", 'system')


async def run_gui_with_brain(brain, personality_name: str = "default", enable_voice: bool = True):
    """
    Run the GUI with the brain, integrating async event loops.
    This is the main entry point for GUI mode.

    Uses qasync to properly integrate Qt event loop with asyncio.
    """
    import qasync
    from gui.hud import create_hud_app
    from core.personality import get_personality
    import sys

    # Create Qt app and HUD (must be in main thread)
    app, hud = create_hud_app()

    # Create bridge
    bridge = GUIBridge(hud)

    # Connect HUD signals to brain
    async def on_send_message(message: str):
        hud.set_input_enabled(False)
        hud.set_status("PROCESSING", "#ffaa00")
        try:
            async for token in brain.think(message):
                # Tokens are already emitted via EventBus -> bridge -> HUD
                pass
        except Exception as e:
            hud.log_error(f"Error: {e}")
        finally:
            hud.set_input_enabled(True)
            hud.set_status("ONLINE", "#00ff88")

    async def on_toggle_voice(enabled: bool):
        if not VOICE_AVAILABLE or not bridge._voice_bridge:
            hud.log_activity("Voz não disponível", 'error')
            return

        if enabled:
            hud.log_activity("Entrada de voz ativada", 'system')
            hud.set_status("LISTENING", "#00aaff")
            await bridge._voice_bridge.start_continuous_listening()
        else:
            hud.log_activity("Entrada de voz desativada", 'system')
            hud.set_status("ONLINE", "#00ff88")
            await bridge._voice_bridge.stop_continuous_listening()

    hud.send_message.connect(lambda msg: asyncio.create_task(on_send_message(msg)))
    hud.toggle_voice.connect(lambda enabled: asyncio.create_task(on_toggle_voice(enabled)))

    # Initialize bridge (subscribes to EventBus)
    await bridge.initialize(enable_voice=enable_voice)

    # Set initial status
    hud.set_status("ONLINE", "#00ff88")
    hud.log_activity("Interface gráfica iniciada", 'system')
    if VOICE_AVAILABLE and enable_voice:
        hud.log_activity("Sistema de voz disponível", 'system')

    # Use qasync to run Qt event loop integrated with asyncio
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Flag to track shutdown
    shutdown_event = asyncio.Event()

    def on_about_to_quit():
        shutdown_event.set()

    app.aboutToQuit.connect(on_about_to_quit)

    try:
        # Run the Qt event loop (which also runs asyncio tasks)
        await shutdown_event.wait()
    finally:
        bridge.async_loop.stop()
        if bridge._voice_bridge:
            await bridge._voice_bridge.shutdown()

    return 0


def run_gui_blocking(brain, personality_name: str = "default", enable_voice: bool = True):
    """Blocking wrapper to run GUI from sync context."""
    return asyncio.run(run_gui_with_brain(brain, personality_name, enable_voice))