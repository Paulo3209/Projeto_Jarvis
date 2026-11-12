"""
Advanced HUD - Sophisticated heads-up display for JARVIS.
Real-time monitoring, device visualization, voice integration, widgets.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.event_bus import EventBus, EventType, get_event_bus

logger = logging.getLogger(__name__)


class WidgetType(Enum):
    """HUD widget types."""
    SYSTEM_STATUS = "system_status"
    DEVICE_LIST = "device_list"
    NETWORK_MAP = "network_map"
    VOICE_STATUS = "voice_status"
    TOOL_ACTIVITY = "tool_activity"
    MEMORY_USAGE = "memory_usage"
    CPU_GPU = "cpu_gpu"
    NETWORK_IO = "network_io"
    ACTIVE_TASKS = "active_tasks"
    NOTIFICATIONS = "notifications"
    QUICK_ACTIONS = "quick_actions"
    CUSTOM = "custom"


class WidgetPosition(Enum):
    """Widget positions on HUD."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    MIDDLE_CENTER = "middle_center"
    MIDDLE_RIGHT = "middle_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"
    FLOATING = "floating"


@dataclass
class HUDWidget:
    """HUD widget configuration."""
    widget_id: str
    widget_type: WidgetType
    title: str
    position: WidgetPosition = WidgetPosition.FLOATING
    size: Tuple[int, int] = (300, 200)
    enabled: bool = True
    refresh_interval: float = 1.0
    config: Dict = field(default_factory=dict)
    z_index: int = 0


@dataclass
class HUDConfig:
    """HUD configuration."""
    width: int = 1920
    height: int = 1080
    opacity: float = 0.9
    theme: str = "dark"  # dark, light, auto
    font_family: str = "JetBrains Mono"
    font_size: int = 12
    accent_color: str = "#00ff88"
    background_color: str = "#1a1a2e"
    border_color: str = "#00ff8888"
    show_fps: bool = True
    auto_hide: bool = False
    hide_delay: float = 5.0
    widgets: List[HUDWidget] = field(default_factory=list)


class HUDTheme(Enum):
    """HUD themes."""
    DARK = "dark"
    LIGHT = "light"
    MATRIX = "matrix"
    CYBERPUNK = "cyberpunk"
    MINIMAL = "minimal"
    HIGH_CONTRAST = "high_contrast"


THEMES = {
    HUDTheme.DARK: {
        "background": "#1a1a2e",
        "foreground": "#e0e0e0",
        "accent": "#00ff88",
        "border": "#00ff8888",
        "widget_bg": "#16213e",
        "widget_border": "#0f3460",
        "text": "#ffffff",
        "text_dim": "#888888",
        "success": "#00ff88",
        "warning": "#ffaa00",
        "error": "#ff4444",
    },
    HUDTheme.LIGHT: {
        "background": "#f0f0f0",
        "foreground": "#333333",
        "accent": "#0077cc",
        "border": "#0077cc88",
        "widget_bg": "#ffffff",
        "widget_border": "#dddddd",
        "text": "#333333",
        "text_dim": "#666666",
        "success": "#00aa00",
        "warning": "#cc8800",
        "error": "#cc0000",
    },
    HUDTheme.MATRIX: {
        "background": "#000000",
        "foreground": "#00ff00",
        "accent": "#00ff00",
        "border": "#00ff0088",
        "widget_bg": "#001100",
        "widget_border": "#003300",
        "text": "#00ff00",
        "text_dim": "#008800",
        "success": "#00ff00",
        "warning": "#ffff00",
        "error": "#ff0000",
    },
    HUDTheme.CYBERPUNK: {
        "background": "#0d0221",
        "foreground": "#ff00ff",
        "accent": "#00ffff",
        "border": "#00ffff88",
        "widget_bg": "#1a0033",
        "widget_border": "#330066",
        "text": "#ffffff",
        "text_dim": "#aa00aa",
        "success": "#00ffff",
        "warning": "#ffff00",
        "error": "#ff0066",
    },
    HUDTheme.MINIMAL: {
        "background": "#ffffff00",  # Transparent
        "foreground": "#333333",
        "accent": "#0066cc",
        "border": "#0066cc44",
        "widget_bg": "#ffffffee",
        "widget_border": "#dddddd",
        "text": "#333333",
        "text_dim": "#999999",
        "success": "#00aa00",
        "warning": "#cc8800",
        "error": "#cc0000",
    },
    HUDTheme.HIGH_CONTRAST: {
        "background": "#000000",
        "foreground": "#ffffff",
        "accent": "#ffff00",
        "border": "#ffff00",
        "widget_bg": "#111111",
        "widget_border": "#ffff00",
        "text": "#ffffff",
        "text_dim": "#cccccc",
        "success": "#00ff00",
        "warning": "#ffff00",
        "error": "#ff0000",
    },
}


class AdvancedHUD:
    """
    Advanced HUD for JARVIS.
    Real-time system monitoring, device visualization, voice integration.
    """

    def __init__(self, config: Optional[HUDConfig] = None):
        self.config = config or HUDConfig()
        self._widgets: Dict[str, HUDWidget] = {}
        self._widget_data: Dict[str, Any] = {}
        self._running = False
        self._event_bus: Optional[EventBus] = None
        self._update_tasks: Dict[str, asyncio.Task] = {}
        self._callbacks: List[Callable] = []
        self._visible = True
        self._last_interaction = time.time()
        self._theme = THEMES[HUDTheme.DARK]

        # Register default widgets
        self._register_default_widgets()

    def _register_default_widgets(self) -> None:
        """Register default HUD widgets."""
        defaults = [
            HUDWidget(
                widget_id="sys_status",
                widget_type=WidgetType.SYSTEM_STATUS,
                title="System Status",
                position=WidgetPosition.TOP_LEFT,
                size=(350, 150),
                refresh_interval=1.0,
            ),
            HUDWidget(
                widget_id="device_list",
                widget_type=WidgetType.DEVICE_LIST,
                title="Connected Devices",
                position=WidgetPosition.TOP_RIGHT,
                size=(350, 300),
                refresh_interval=5.0,
            ),
            HUDWidget(
                widget_id="voice_status",
                widget_type=WidgetType.VOICE_STATUS,
                title="Voice System",
                position=WidgetPosition.BOTTOM_LEFT,
                size=(300, 100),
                refresh_interval=0.5,
            ),
            HUDWidget(
                widget_id="tool_activity",
                widget_type=WidgetType.TOOL_ACTIVITY,
                title="Tool Activity",
                position=WidgetPosition.BOTTOM_RIGHT,
                size=(400, 200),
                refresh_interval=0.5,
            ),
            HUDWidget(
                widget_id="active_tasks",
                widget_type=WidgetType.ACTIVE_TASKS,
                title="Active Tasks",
                position=WidgetPosition.MIDDLE_LEFT,
                size=(350, 250),
                refresh_interval=1.0,
            ),
            HUDWidget(
                widget_id="notifications",
                widget_type=WidgetType.NOTIFICATIONS,
                title="Notifications",
                position=WidgetPosition.MIDDLE_RIGHT,
                size=(350, 200),
                refresh_interval=1.0,
            ),
        ]

        for widget in defaults:
            self._widgets[widget.widget_id] = widget

    def set_theme(self, theme: HUDTheme) -> None:
        """Set HUD theme."""
        self._theme = THEMES.get(theme, THEMES[HUDTheme.DARK])
        if self.config.theme == "auto":
            # Could detect system theme
            pass

    def add_widget(self, widget: HUDWidget) -> None:
        """Add custom widget."""
        self._widgets[widget.widget_id] = widget

    def remove_widget(self, widget_id: str) -> bool:
        """Remove widget."""
        if widget_id in self._widgets:
            del self._widgets[widget_id]
            self._widget_data.pop(widget_id, None)
            return True
        return False

    def get_widget(self, widget_id: str) -> Optional[HUDWidget]:
        """Get widget by ID."""
        return self._widgets.get(widget_id)

    def update_widget_config(self, widget_id: str, config: Dict) -> bool:
        """Update widget configuration."""
        if widget_id in self._widgets:
            self._widgets[widget_id].config.update(config)
            return True
        return False

    def set_widget_position(self, widget_id: str, position: WidgetPosition) -> bool:
        """Set widget position."""
        if widget_id in self._widgets:
            self._widgets[widget_id].position = position
            return True
        return False

    def set_widget_size(self, widget_id: str, width: int, height: int) -> bool:
        """Set widget size."""
        if widget_id in self._widgets:
            self._widgets[widget_id].size = (width, height)
            return True
        return False

    def enable_widget(self, widget_id: str) -> bool:
        """Enable widget."""
        if widget_id in self._widgets:
            self._widgets[widget_id].enabled = True
            return True
        return False

    def disable_widget(self, widget_id: str) -> bool:
        """Disable widget."""
        if widget_id in self._widgets:
            self._widgets[widget_id].enabled = False
            return True
        return False

    async def initialize(self) -> None:
        """Initialize HUD and event subscriptions."""
        self._event_bus = await get_event_bus()

        # Subscribe to events
        self._event_bus.subscribe_async(EventType.TOOL_CALLED, self._on_tool_called)
        self._event_bus.subscribe_async(EventType.TOOL_COMPLETED, self._on_tool_completed)
        self._event_bus.subscribe_async(EventType.TOOL_FAILED, self._on_tool_failed)
        self._event_bus.subscribe_async(EventType.STATUS_CHANGE, self._on_status_change)
        self._event_bus.subscribe_async(EventType.VOICE_SPEAK_START, self._on_voice_start)
        self._event_bus.subscribe_async(EventType.VOICE_SPEAK_END, self._on_voice_end)
        self._event_bus.subscribe_async(EventType.VOICE_TRANSCRIPTION, self._on_voice_transcription)
        self._event_bus.subscribe_async(EventType.DEVICE_CONNECTED, self._on_device_connected)
        self._event_bus.subscribe_async(EventType.DEVICE_DISCONNECTED, self._on_device_disconnected)

        # Start widget update loops
        for widget_id, widget in self._widgets.items():
            if widget.enabled:
                self._update_tasks[widget_id] = asyncio.create_task(
                    self._widget_update_loop(widget_id)
                )

        self._running = True
        logger.info("Advanced HUD initialized")

    async def _widget_update_loop(self, widget_id: str) -> None:
        """Update loop for a widget."""
        widget = self._widgets[widget_id]
        while self._running and widget.enabled:
            try:
                await self._update_widget(widget_id)
            except Exception as e:
                logger.error(f"Widget update error ({widget_id}): {e}")

            await asyncio.sleep(widget.refresh_interval)

    async def _update_widget(self, widget_id: str) -> None:
        """Update widget data."""
        widget = self._widgets[widget_id]

        if widget.widget_type == WidgetType.SYSTEM_STATUS:
            data = await self._get_system_status()
        elif widget.widget_type == WidgetType.DEVICE_LIST:
            data = await self._get_device_list()
        elif widget.widget_type == WidgetType.VOICE_STATUS:
            data = await self._get_voice_status()
        elif widget.widget_type == WidgetType.TOOL_ACTIVITY:
            data = await self._get_tool_activity()
        elif widget.widget_type == WidgetType.ACTIVE_TASKS:
            data = await self._get_active_tasks()
        elif widget.widget_type == WidgetType.NOTIFICATIONS:
            data = await self._get_notifications()
        elif widget.widget_type == WidgetType.CPU_GPU:
            data = await self._get_cpu_gpu()
        elif widget.widget_type == WidgetType.MEMORY_USAGE:
            data = await self._get_memory_usage()
        elif widget.widget_type == WidgetType.NETWORK_IO:
            data = await self._get_network_io()
        else:
            data = {}

        self._widget_data[widget_id] = {
            "widget": widget,
            "data": data,
            "updated_at": time.time(),
        }

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(widget_id, data)
            except Exception as e:
                logger.error(f"HUD callback error: {e}")

    async def _get_system_status(self) -> Dict:
        """Get system status data."""
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('C:' if psutil.WINDOWS else '/')

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_gb": memory.used / (1024**3),
            "memory_total_gb": memory.total / (1024**3),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024**3),
            "uptime": time.time() - psutil.boot_time(),
            "processes": len(psutil.pids()),
        }

    async def _get_device_list(self) -> Dict:
        """Get connected devices."""
        from devices.device_registry import get_device_manager
        try:
            manager = get_device_manager()
            devices = manager.list_devices()
            return {
                "devices": [
                    {
                        "device_id": d.device_id,
                        "name": d.name,
                        "type": d.device_type.value,
                        "status": d.connection_status.value,
                        "protocol": d.protocol.value,
                        "address": d.address,
                        "trusted": d.trusted,
                    }
                    for d in devices
                ],
                "total": len(devices),
                "online": len([d for d in devices if d.connection_status.value == "connected"]),
            }
        except Exception:
            return {"devices": [], "total": 0, "online": 0}

    async def _get_voice_status(self) -> Dict:
        """Get voice system status."""
        try:
            from voice.bridge import _voice_bridge
            bridge = _voice_bridge
            if bridge:
                return {
                    "initialized": bridge._initialized,
                    "listening": bridge._listening_task is not None and not bridge._listening_task.done(),
                    "speaking": bridge._tts is not None and hasattr(bridge._tts, '_playing'),
                    "wake_word": bridge.settings.wake_word,
                    "auto_speak": bridge.settings.auto_speak,
                }
        except Exception:
            pass
        return {"initialized": False, "listening": False, "speaking": False}

    async def _get_tool_activity(self) -> Dict:
        """Get recent tool activity."""
        # This would track from event bus
        return {
            "recent": [],  # Would be populated from events
            "total_calls": 0,
            "success_rate": 1.0,
        }

    async def _get_active_tasks(self) -> Dict:
        """Get active tasks."""
        from agents.executor import _executor
        try:
            executor = _executor
            if executor:
                executions = executor.get_active_executions()
                return {
                    "executions": [
                        {
                            "id": ex.execution_id,
                            "workflow": ex.workflow_id,
                            "status": ex.status.value,
                            "progress": ex.progress,
                            "started": ex.started_at.isoformat() if ex.started_at else None,
                        }
                        for ex in executions
                    ],
                    "count": len(executions),
                }
        except Exception:
            pass
        return {"executions": [], "count": 0}

    async def _get_notifications(self) -> Dict:
        """Get notifications."""
        from android_app.notifications import get_notification_manager
        try:
            manager = get_notification_manager()
            # Would get from manager
            return {"notifications": [], "unread": 0}
        except Exception:
            return {"notifications": [], "unread": 0}

    async def _get_cpu_gpu(self) -> Dict:
        """Get CPU/GPU usage."""
        import psutil

        cpu_per_core = psutil.cpu_percent(percpu=True, interval=0.1)

        gpu_info = {}
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            for i, gpu in enumerate(gpus):
                gpu_info[f"gpu_{i}"] = {
                    "name": gpu.name,
                    "load": gpu.load * 100,
                    "memory_used": gpu.memoryUsed,
                    "memory_total": gpu.memoryTotal,
                    "temperature": gpu.temperature,
                }
        except Exception:
            pass

        return {
            "cpu_overall": sum(cpu_per_core) / len(cpu_per_core),
            "cpu_per_core": cpu_per_core,
            "gpus": gpu_info,
        }

    async def _get_memory_usage(self) -> Dict:
        """Get detailed memory usage."""
        import psutil

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            "virtual": {
                "total": mem.total,
                "available": mem.available,
                "used": mem.used,
                "percent": mem.percent,
            },
            "swap": {
                "total": swap.total,
                "used": swap.used,
                "percent": swap.percent,
            },
        }

    async def _get_network_io(self) -> Dict:
        """Get network I/O."""
        import psutil

        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }

    # Event handlers
    async def _on_tool_called(self, event) -> None:
        self._last_interaction = time.time()

    async def _on_tool_completed(self, event) -> None:
        pass

    async def _on_tool_failed(self, event) -> None:
        pass

    async def _on_status_change(self, event) -> None:
        pass

    async def _on_voice_start(self, event) -> None:
        pass

    async def _on_voice_end(self, event) -> None:
        pass

    async def _on_voice_transcription(self, event) -> None:
        pass

    async def _on_device_connected(self, event) -> None:
        pass

    async def _on_device_disconnected(self, event) -> None:
        pass

    def add_callback(self, callback: Callable) -> None:
        """Add data update callback."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        """Remove callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_widget_data(self, widget_id: str) -> Optional[Dict]:
        """Get current widget data."""
        return self._widget_data.get(widget_id)

    def get_all_widget_data(self) -> Dict:
        """Get all widget data."""
        return self._widget_data.copy()

    def get_layout(self) -> Dict:
        """Get HUD layout configuration."""
        return {
            "width": self.config.width,
            "height": self.config.height,
            "theme": self._theme,
            "widgets": [
                {
                    "widget_id": w.widget_id,
                    "type": w.widget_type.value,
                    "title": w.title,
                    "position": w.position.value,
                    "size": w.size,
                    "enabled": w.enabled,
                    "z_index": w.z_index,
                }
                for w in self._widgets.values()
                if w.enabled
            ],
        }

    def set_visible(self, visible: bool) -> None:
        """Set HUD visibility."""
        self._visible = visible

    def is_visible(self) -> bool:
        """Check if HUD is visible."""
        if self.config.auto_hide:
            return time.time() - self._last_interaction < self.config.hide_delay
        return self._visible

    async def shutdown(self) -> None:
        """Shutdown HUD."""
        self._running = False

        for task in self._update_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._update_tasks.clear()
        logger.info("Advanced HUD shutdown")


# Global instance
_advanced_hud: Optional[AdvancedHUD] = None


def get_advanced_hud(config: Optional[HUDConfig] = None) -> AdvancedHUD:
    """Get global advanced HUD instance."""
    global _advanced_hud
    if _advanced_hud is None:
        _advanced_hud = AdvancedHUD(config)
    return _advanced_hud