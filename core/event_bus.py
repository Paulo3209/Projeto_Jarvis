"""
Event Bus - Central pub/sub system for JARVIS components.
Allows decoupled communication between Brain, Router, Tools, Memory, GUI, Voice.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any, Awaitable
from enum import Enum
import weakref


class EventType(Enum):
    # User interaction
    USER_MESSAGE = "user_message"
    ASSISTANT_TOKEN = "assistant_token"
    ASSISTANT_RESPONSE_COMPLETE = "assistant_response_complete"

    # Tool execution
    TOOL_CALLED = "tool_called"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"

    # Memory
    MEMORY_SAVED = "memory_saved"
    MEMORY_RECALLED = "memory_recalled"

    # System
    SYSTEM_INFO = "system_info"
    ERROR = "error"
    STATUS_CHANGE = "status_change"

    # Voice (future M3)
    VOICE_START_LISTENING = "voice_start_listening"
    VOICE_STOP_LISTENING = "voice_stop_listening"
    VOICE_TRANSCRIPTION = "voice_transcription"
    VOICE_SPEAK_START = "voice_speak_start"
    VOICE_SPEAK_END = "voice_speak_end"

    # GUI/HUD (future M2)
    HUD_UPDATE_STATUS = "hud_update_status"
    HUD_UPDATE_METRICS = "hud_update_metrics"
    HUD_LOG_ACTIVITY = "hud_log_activity"


@dataclass
class Event:
    """Base event class."""
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "data": self.data,
        }


# Specific event dataclasses for type hints
@dataclass
class UserMessageEvent(Event):
    def __init__(self, message: str, source: str = "cli"):
        super().__init__(
            type=EventType.USER_MESSAGE,
            source=source,
            data={"message": message}
        )


@dataclass
class AssistantTokenEvent(Event):
    def __init__(self, token: str, source: str = "brain"):
        super().__init__(
            type=EventType.ASSISTANT_TOKEN,
            source=source,
            data={"token": token}
        )


@dataclass
class AssistantResponseCompleteEvent(Event):
    def __init__(self, full_response: str, source: str = "brain"):
        super().__init__(
            type=EventType.ASSISTANT_RESPONSE_COMPLETE,
            source=source,
            data={"full_response": full_response}
        )


@dataclass
class ToolCalledEvent(Event):
    def __init__(self, name: str, arguments: dict, call_id: str, source: str = "brain"):
        super().__init__(
            type=EventType.TOOL_CALLED,
            source=source,
            data={"name": name, "arguments": arguments, "call_id": call_id}
        )


@dataclass
class ToolCompletedEvent(Event):
    def __init__(self, name: str, result: dict, call_id: str, source: str = "router"):
        super().__init__(
            type=EventType.TOOL_COMPLETED,
            source=source,
            data={"name": name, "result": result, "call_id": call_id}
        )


@dataclass
class ToolFailedEvent(Event):
    def __init__(self, name: str, error: str, call_id: str, source: str = "router"):
        super().__init__(
            type=EventType.TOOL_FAILED,
            source=source,
            data={"name": name, "error": error, "call_id": call_id}
        )


@dataclass
class MemorySavedEvent(Event):
    def __init__(self, content: str, source: str = "memory"):
        super().__init__(
            type=EventType.MEMORY_SAVED,
            source=source,
            data={"content": content}
        )


@dataclass
class MemoryRecalledEvent(Event):
    def __init__(self, query: str, memories: list, source: str = "memory"):
        super().__init__(
            type=EventType.MEMORY_RECALLED,
            source=source,
            data={"query": query, "memories": memories}
        )


@dataclass
class ErrorEvent(Event):
    def __init__(self, error: str, source: str = "system"):
        super().__init__(
            type=EventType.ERROR,
            source=source,
            data={"error": error}
        )


@dataclass
class StatusChangeEvent(Event):
    def __init__(self, status: str, source: str = "system"):
        super().__init__(
            type=EventType.STATUS_CHANGE,
            source=source,
            data={"status": status}
        )


# Voice events
@dataclass
class VoiceTranscriptionEvent(Event):
    def __init__(self, text: str, source: str = "voice"):
        super().__init__(
            type=EventType.VOICE_TRANSCRIPTION,
            source=source,
            data={"text": text}
        )


@dataclass
class VoiceSpeakStartEvent(Event):
    def __init__(self, text: str, source: str = "voice"):
        super().__init__(
            type=EventType.VOICE_SPEAK_START,
            source=source,
            data={"text": text}
        )


@dataclass
class VoiceSpeakEndEvent(Event):
    def __init__(self, text: str, source: str = "voice"):
        super().__init__(
            type=EventType.VOICE_SPEAK_END,
            source=source,
            data={"text": text}
        )


@dataclass
class VoiceStartListeningEvent(Event):
    def __init__(self, source: str = "voice"):
        super().__init__(
            type=EventType.VOICE_START_LISTENING,
            source=source,
            data={}
        )


@dataclass
class VoiceStopListeningEvent(Event):
    def __init__(self, source: str = "voice"):
        super().__init__(
            type=EventType.VOICE_STOP_LISTENING,
            source=source,
            data={}
        )


# Type alias for event handlers
EventHandler = Callable[[Event], Any]
AsyncEventHandler = Callable[[Event], Awaitable[Any]]


class EventBus:
    """
    Singleton event bus for pub/sub communication.
    Supports both sync and async handlers.
    """

    _instance: EventBus | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._async_handlers: dict[EventType, list[AsyncEventHandler]] = {}
        self._event_history: list[Event] = []
        self._max_history = 1000
        self._initialized = True

    @classmethod
    async def get_instance(cls) -> EventBus:
        """Async-safe singleton getter."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = EventBus()
            return cls._instance

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a synchronous handler to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def subscribe_async(self, event_type: EventType, handler: AsyncEventHandler) -> None:
        """Subscribe an asynchronous handler to an event type."""
        if event_type not in self._async_handlers:
            self._async_handlers[event_type] = []
        self._async_handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> bool:
        """Unsubscribe a handler. Returns True if found and removed."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        if event_type in self._async_handlers:
            try:
                self._async_handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    def emit(self, event: Event) -> None:
        """Emit an event to all synchronous handlers (fire-and-forget)."""
        self._store_event(event)
        self._call_sync_handlers(event)
        # Schedule async handlers
        self._schedule_async_handlers(event)

    async def emit_async(self, event: Event) -> None:
        """Emit an event and await all async handlers."""
        self._store_event(event)
        self._call_sync_handlers(event)
        await self._call_async_handlers(event)

    def _store_event(self, event: Event) -> None:
        """Store event in history."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

    def _call_sync_handlers(self, event: Event) -> None:
        """Call all synchronous handlers for an event."""
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # Log error but don't break other handlers
                print(f"[EventBus] Sync handler error for {event.type}: {e}")

    def _schedule_async_handlers(self, event: Event) -> None:
        """Schedule async handlers to run in the background."""
        handlers = self._async_handlers.get(event.type, [])
        for handler in handlers:
            try:
                asyncio.create_task(self._safe_async_call(handler, event))
            except RuntimeError:
                # No event loop running - can't schedule
                pass

    async def _call_async_handlers(self, event: Event) -> None:
        """Call all async handlers and await them."""
        handlers = self._async_handlers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                print(f"[EventBus] Async handler error for {event.type}: {e}")

    async def _safe_async_call(self, handler: AsyncEventHandler, event: Event) -> None:
        """Safely call an async handler, catching exceptions."""
        try:
            await handler(event)
        except Exception as e:
            print(f"[EventBus] Background async handler error for {event.type}: {e}")

    def get_history(self, event_type: EventType | None = None, limit: int = 100) -> list[Event]:
        """Get recent event history, optionally filtered by type."""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()


# Convenience function for easy access
async def get_event_bus() -> EventBus:
    """Get the global EventBus instance."""
    return await EventBus.get_instance()


# Decorator for easy subscription
def on_event(event_type: EventType):
    """Decorator to register an async handler for an event type."""
    def decorator(func: AsyncEventHandler) -> AsyncEventHandler:
        async def register():
            bus = await get_event_bus()
            bus.subscribe_async(event_type, func)
        # Schedule registration
        try:
            asyncio.create_task(register())
        except RuntimeError:
            # No loop yet, will register on first emit
            pass
        return func
    return decorator


def on_event_sync(event_type: EventType):
    """Decorator to register a sync handler for an event type."""
    def decorator(func: EventHandler) -> EventHandler:
        async def register():
            bus = await get_event_bus()
            bus.subscribe(event_type, func)
        try:
            asyncio.create_task(register())
        except RuntimeError:
            pass
        return func
    return decorator