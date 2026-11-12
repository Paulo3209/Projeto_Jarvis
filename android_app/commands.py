"""
Commands Module - Mobile command handling for Android app.
Routes commands from mobile app to JARVIS systems.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.event_bus import EventBus, get_event_bus


class CommandType(Enum):
    """Mobile command types."""
    TOOL_EXECUTE = "tool_execute"
    DEVICE_CONTROL = "device_control"
    VOICE_INPUT = "voice_input"
    SCREEN_CAPTURE = "screen_capture"
    SYSTEM_QUERY = "system_query"
    AUTOMATION_RUN = "automation_run"
    SECURITY_ACTION = "security_action"
    CONFIG_CHANGE = "config_change"


@dataclass
class MobileCommand:
    """Command from mobile app."""
    command_id: str
    command_type: CommandType
    payload: Dict
    user_id: str
    timestamp: float
    priority: int = 1


class CommandHandler:
    """
    Handles commands from mobile app.
    Routes to appropriate JARVIS subsystems.
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._handlers: Dict[CommandType, callable] = {}
        self._register_handlers()

    async def initialize(self) -> None:
        """Initialize handler."""
        self._event_bus = await get_event_bus()

    def _register_handlers(self) -> None:
        """Register command type handlers."""
        self._handlers = {
            CommandType.TOOL_EXECUTE: self._handle_tool_execute,
            CommandType.DEVICE_CONTROL: self._handle_device_control,
            CommandType.VOICE_INPUT: self._handle_voice_input,
            CommandType.SCREEN_CAPTURE: self._handle_screen_capture,
            CommandType.SYSTEM_QUERY: self._handle_system_query,
            CommandType.AUTOMATION_RUN: self._handle_automation_run,
            CommandType.SECURITY_ACTION: self._handle_security_action,
            CommandType.CONFIG_CHANGE: self._handle_config_change,
        }

    async def handle_command(self, command: MobileCommand) -> Dict:
        """Route command to appropriate handler."""
        handler = self._handlers.get(command.command_type)
        if not handler:
            return {"success": False, "error": f"Unknown command type: {command.command_type}"}

        try:
            return await handler(command)
        except Exception as e:
            return {"success": False, "error": f"Handler error: {type(e).__name__}: {e}"}

    async def _handle_tool_execute(self, command: MobileCommand) -> Dict:
        """Execute a JARVIS tool."""
        from core.brain import Brain
        brain = Brain.__new__(Brain)
        brain.router = __import__('core.router', fromlist=['Router']).Router()
        brain.router._refresh_tool_cache()

        tool_name = command.payload.get("tool")
        arguments = command.payload.get("arguments", {})

        if not tool_name:
            return {"success": False, "error": "Tool name required"}

        result = await brain.router.execute_async(tool_name, arguments)
        return result

    async def _handle_device_control(self, command: MobileCommand) -> Dict:
        """Control a connected device."""
        from devices.device_registry import get_device_manager
        manager = get_device_manager()

        device_id = command.payload.get("device_id")
        action = command.payload.get("action")
        params = command.payload.get("params", {})

        if not device_id or not action:
            return {"success": False, "error": "device_id and action required"}

        if action == "connect":
            return await manager.connect_device(device_id)
        elif action == "disconnect":
            return await manager.disconnect_device(device_id)
        elif action == "command":
            cmd = params.get("command")
            args = params.get("args", {})
            if not cmd:
                return {"success": False, "error": "command required"}
            if not manager.is_connected(device_id):
                await manager.connect_device(device_id)
            return await manager.execute_command(device_id, cmd, args)
        elif action == "status":
            device = manager.get_device(device_id)
            if not device:
                return {"success": False, "error": "Device not found"}
            return {"success": True, "device": device.to_dict()}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    async def _handle_voice_input(self, command: MobileCommand) -> Dict:
        """Process voice input from mobile."""
        text = command.payload.get("text")
        if not text:
            return {"success": False, "error": "Text required"}

        if self._event_bus:
            from core.event_bus import UserMessageEvent
            self._event_bus.emit(UserMessageEvent(text, source="android_voice"))

        return {"success": True, "message": "Voice input queued for processing"}

    async def _handle_screen_capture(self, command: MobileCommand) -> Dict:
        """Capture screen and return base64 image."""
        from vision.screen import get_screen_manager
        import base64

        screen = get_screen_manager()
        monitor = command.payload.get("monitor", 0)
        capture = await screen.capture(monitor=monitor)
        img_base64 = base64.b64encode(capture.image_data).decode()

        return {
            "success": True,
            "image": img_base64,
            "width": capture.width,
            "height": capture.height,
            "monitor": monitor,
            "format": "png",
        }

    async def _handle_system_query(self, command: MobileCommand) -> Dict:
        """Query system status."""
        query_type = command.payload.get("query_type", "status")

        if query_type == "status":
            from core.brain import Brain
            brain = Brain.__new__(Brain)
            brain.router = __import__('core.router', fromlist=['Router']).Router()
            brain.router._refresh_tool_cache()
            result = await brain.router.execute_async("get_system_info", {})
            return result

        elif query_type == "devices":
            from devices.device_registry import get_device_manager
            manager = get_device_manager()
            devices = manager.list_devices()
            return {"success": True, "devices": [d.to_dict() for d in devices]}

        elif query_type == "tools":
            from core.plugin_system import get_all_tools
            tools = get_all_tools()
            return {
                "success": True,
                "tools": [
                    {"name": t.name, "description": t.description, "category": t.category.value}
                    for t in tools
                ]
            }

        elif query_type == "clients":
            from android_app.bridge import get_android_bridge
            bridge = await get_android_bridge()
            return {"success": True, "clients": bridge.get_connected_clients()}

        else:
            return {"success": False, "error": f"Unknown query type: {query_type}"}

    async def _handle_automation_run(self, command: MobileCommand) -> Dict:
        """Run automation workflow."""
        from agents.executor import executor_run_adhoc

        tasks = command.payload.get("tasks", [])
        mode = command.payload.get("mode", "sequential")

        if not tasks:
            return {"success": False, "error": "Tasks required"}

        return await executor_run_adhoc(tasks, mode)

    async def _handle_security_action(self, command: MobileCommand) -> Dict:
        """Execute security action."""
        action = command.payload.get("action")

        if action == "lock_device":
            from security.device_registry import secure_device_block
            return await secure_device_block(
                command.payload.get("device_id"),
                command.payload.get("reason", "Mobile lock"),
                command.user_id
            )

        elif action == "unlock_device":
            from security.device_registry import secure_device_unblock
            return await secure_device_unblock(
                command.payload.get("device_id"),
                command.user_id
            )

        elif action == "revoke_session":
            from security.authentication import auth_revoke_session
            return await auth_revoke_session(command.payload.get("session_id"))

        elif action == "audit_log":
            from security.audit import audit_log
            return await audit_log(
                command.payload.get("event_type", "mobile_action"),
                command.user_id,
                "android_app",
                command.payload.get("action", "unknown"),
                "success",
                command.payload.get("details"),
                "info"
            )

        else:
            return {"success": False, "error": f"Unknown security action: {action}"}

    async def _handle_config_change(self, command: MobileCommand) -> Dict:
        """Change configuration."""
        config_type = command.payload.get("config_type")
        value = command.payload.get("value")

        if config_type == "voice_wake_word":
            from voice.bridge import get_voice_bridge
            bridge = await get_voice_bridge()
            bridge.set_wake_word(value)
            return {"success": True, "message": f"Wake word changed to {value}"}

        elif config_type == "voice_auto_speak":
            from voice.bridge import get_voice_bridge
            bridge = await get_voice_bridge()
            bridge.set_auto_speak(value)
            return {"success": True, "message": f"Auto-speak {'enabled' if value else 'disabled'}"}

        elif config_type == "personality":
            # Would need to restart brain with new personality
            return {"success": False, "error": "Personality change requires restart"}

        else:
            return {"success": False, "error": f"Unknown config type: {config_type}"}


async def handle_mobile_command(
    command_type: str,
    payload: Dict,
    user_id: str,
) -> Dict:
    """Convenience function to handle mobile command."""
    handler = CommandHandler()
    await handler.initialize()

    try:
        cmd_type = CommandType(command_type)
    except ValueError:
        return {"success": False, "error": f"Invalid command type: {command_type}"}

    import time
    import secrets
    command = MobileCommand(
        command_id=secrets.token_hex(8),
        command_type=cmd_type,
        payload=payload,
        user_id=user_id,
        timestamp=time.time(),
    )

    return await handler.handle_command(command)