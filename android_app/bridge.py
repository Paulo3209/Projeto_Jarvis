"""
Android Bridge - WebSocket/API bridge for Flutter app communication.
Handles authentication, command routing, and real-time updates.
"""
from __future__ import annotations
import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum

from core.event_bus import EventBus, EventType, get_event_bus
from security.authentication import get_jwt_manager, get_api_key_manager

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Android app connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class AndroidConfig:
    """Configuration for Android bridge."""
    host: str = "0.0.0.0"
    port: int = 8765
    ssl_enabled: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    auth_required: bool = True
    jwt_secret: Optional[str] = None
    max_connections: int = 10
    heartbeat_interval: int = 30
    command_timeout: int = 60


@dataclass
class MobileClient:
    """Connected mobile client."""
    client_id: str
    websocket: Any
    authenticated: bool = False
    user_id: Optional[str] = None
    device_name: Optional[str] = None
    device_info: Dict = field(default_factory=dict)
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    pending_commands: Dict[str, asyncio.Future] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)


class AndroidBridge:
    """
    WebSocket bridge for Android app communication.
    Handles auth, command routing, notifications, and real-time sync.
    """

    def __init__(self, config: Optional[AndroidConfig] = None):
        self.config = config or AndroidConfig()
        self._server: Optional[asyncio.Server] = None
        self._clients: Dict[str, MobileClient] = {}
        self._running = False
        self._event_bus: Optional[EventBus] = None
        self._jwt_manager = get_jwt_manager()
        self._api_key_manager = get_api_key_manager()
        self._command_handlers: Dict[str, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default command handlers."""
        self._command_handlers = {
            "ping": self._handle_ping,
            "get_status": self._handle_get_status,
            "execute_tool": self._handle_execute_tool,
            "get_devices": self._handle_get_devices,
            "device_command": self._handle_device_command,
            "get_screen": self._handle_get_screen,
            "voice_command": self._handle_voice_command,
            "subscribe_events": self._handle_subscribe_events,
            "unsubscribe_events": self._handle_unsubscribe_events,
        }

    async def initialize(self) -> None:
        """Initialize the bridge and start WebSocket server."""
        self._event_bus = await get_event_bus()
        await self._start_server()
        logger.info(f"Android Bridge started on {self.config.host}:{self.config.port}")

    async def _start_server(self) -> None:
        """Start WebSocket server."""
        import websockets

        async def handler(websocket, path):
            client_id = secrets.token_hex(8)
            client = MobileClient(client_id=client_id, websocket=websocket)
            self._clients[client_id] = client

            try:
                await self._handle_connection(client)
            except Exception as e:
                logger.error(f"Client {client_id} error: {e}")
            finally:
                await self._disconnect_client(client_id)

        self._server = await websockets.serve(
            handler,
            self.config.host,
            self.config.port,
            ssl=None,  # SSL context would be created if enabled
            max_size=10 * 1024 * 1024,  # 10MB max message
            ping_interval=self.config.heartbeat_interval,
            ping_timeout=10,
        )

        self._running = True

    async def _handle_connection(self, client: MobileClient) -> None:
        """Handle incoming messages from a client."""
        async for message in client.websocket:
            try:
                data = json.loads(message)
                await self._process_message(client, data)
            except json.JSONDecodeError:
                await self._send_error(client, "invalid_json", "Invalid JSON format")
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await self._send_error(client, "processing_error", str(e))

    async def _process_message(self, client: MobileClient, data: Dict) -> None:
        """Process incoming message based on type."""
        msg_type = data.get("type")
        request_id = data.get("request_id")

        if msg_type == "auth":
            await self._handle_auth(client, data, request_id)
        elif msg_type == "command":
            await self._handle_command(client, data, request_id)
        elif msg_type == "heartbeat":
            await self._handle_heartbeat(client, request_id)
        elif msg_type == "event_ack":
            # Client acknowledged event
            pass
        else:
            await self._send_error(client, "unknown_type", f"Unknown message type: {msg_type}", request_id)

    async def _handle_auth(self, client: MobileClient, data: Dict, request_id: Optional[str]) -> None:
        """Handle authentication."""
        auth_type = data.get("auth_type")  # "jwt" or "api_key"
        credential = data.get("credential")

        if not self.config.auth_required:
            client.authenticated = True
            client.user_id = "anonymous"
            await self._send_response(client, {"status": "authenticated", "user_id": "anonymous"}, request_id)
            return

        try:
            if auth_type == "jwt":
                result = await self._jwt_manager.verify_token(credential)
                if result.get("success"):
                    client.authenticated = True
                    client.user_id = result.get("subject")
                    await self._send_response(client, {"status": "authenticated", "user_id": client.user_id}, request_id)
                else:
                    await self._send_error(client, "auth_failed", "Invalid JWT", request_id)

            elif auth_type == "api_key":
                result = await self._api_key_manager.validate_key(credential)
                if result.get("success"):
                    client.authenticated = True
                    client.user_id = result.get("key_info", {}).get("name", "api_user")
                    await self._send_response(client, {"status": "authenticated", "user_id": client.user_id}, request_id)
                else:
                    await self._send_error(client, "auth_failed", "Invalid API key", request_id)

            else:
                await self._send_error(client, "auth_failed", "Unsupported auth type", request_id)

        except Exception as e:
            await self._send_error(client, "auth_error", str(e), request_id)

    async def _handle_command(self, client: MobileClient, data: Dict, request_id: Optional[str]) -> None:
        """Handle command execution."""
        if self.config.auth_required and not client.authenticated:
            await self._send_error(client, "unauthorized", "Authentication required", request_id)
            return

        command = data.get("command")
        params = data.get("params", {})

        handler = self._command_handlers.get(command)
        if not handler:
            await self._send_error(client, "unknown_command", f"Unknown command: {command}", request_id)
            return

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                handler(client, params),
                timeout=self.config.command_timeout
            )
            await self._send_response(client, result, request_id)
        except asyncio.TimeoutError:
            await self._send_error(client, "timeout", "Command timed out", request_id)
        except Exception as e:
            await self._send_error(client, "execution_error", str(e), request_id)

    async def _handle_heartbeat(self, client: MobileClient, request_id: Optional[str]) -> None:
        """Handle heartbeat."""
        client.last_heartbeat = datetime.now()
        await self._send_response(client, {"status": "alive", "timestamp": time.time()}, request_id)

    # Default command handlers
    async def _handle_ping(self, client: MobileClient, params: Dict) -> Dict:
        return {"pong": True, "timestamp": time.time()}

    async def _handle_get_status(self, client: MobileClient, params: Dict) -> Dict:
        from core.brain import Brain
        from core.personality import MINIMAL_PERSONALITY
        # Return system status
        return {
            "status": "online",
            "clients_connected": len(self._clients),
            "timestamp": time.time(),
        }

    async def _handle_execute_tool(self, client: MobileClient, params: Dict) -> Dict:
        from core.brain import Brain
        brain = Brain.__new__(Brain)
        brain.router = __import__('core.router', fromlist=['Router']).Router()
        brain.router._refresh_tool_cache()

        tool_name = params.get("tool")
        arguments = params.get("arguments", {})

        if not tool_name:
            return {"success": False, "error": "Tool name required"}

        result = await brain.router.execute_async(tool_name, arguments)
        return result

    async def _handle_get_devices(self, client: MobileClient, params: Dict) -> Dict:
        from devices.device_registry import get_device_manager
        manager = get_device_manager()
        devices = manager.list_devices()
        return {"success": True, "devices": [d.to_dict() for d in devices]}

    async def _handle_device_command(self, client: MobileClient, params: Dict) -> Dict:
        from devices.device_registry import get_device_manager
        manager = get_device_manager()
        device_id = params.get("device_id")
        command = params.get("command")
        args = params.get("args", {})

        if not device_id or not command:
            return {"success": False, "error": "device_id and command required"}

        device = manager.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}

        if not manager.is_connected(device_id):
            await manager.connect_device(device_id)

        return await manager.execute_command(device_id, command, args)

    async def _handle_get_screen(self, client: MobileClient, params: Dict) -> Dict:
        from vision.screen import get_screen_manager
        screen = get_screen_manager()
        monitor = params.get("monitor", 0)
        capture = await screen.capture(monitor=monitor)
        import base64
        img_base64 = base64.b64encode(capture.image_data).decode()
        return {
            "success": True,
            "image": img_base64,
            "width": capture.width,
            "height": capture.height,
            "monitor": monitor,
        }

    async def _handle_voice_command(self, client: MobileClient, params: Dict) -> Dict:
        from voice.bridge import get_voice_bridge
        bridge = await get_voice_bridge()
        text = params.get("text")
        if not text:
            return {"success": False, "error": "Text required"}
        # Inject as user message
        if self._event_bus:
            from core.event_bus import UserMessageEvent
            self._event_bus.emit(UserMessageEvent(text, source="android_app"))
        return {"success": True, "message": "Voice command queued"}

    async def _handle_subscribe_events(self, client: MobileClient, params: Dict) -> Dict:
        event_types = params.get("events", [])
        client.capabilities.extend(event_types)
        return {"success": True, "subscribed": event_types}

    async def _handle_unsubscribe_events(self, client: MobileClient, params: Dict) -> Dict:
        event_types = params.get("events", [])
        for et in event_types:
            if et in client.capabilities:
                client.capabilities.remove(et)
        return {"success": True, "unsubscribed": event_types}

    async def _send_response(self, client: MobileClient, data: Dict, request_id: Optional[str]) -> None:
        """Send response to client."""
        message = {
            "type": "response",
            "request_id": request_id,
            "data": data,
            "timestamp": time.time(),
        }
        await self._send_message(client, message)

    async def _send_error(self, client: MobileClient, code: str, message: str, request_id: Optional[str] = None) -> None:
        """Send error to client."""
        await self._send_response(client, {
            "success": False,
            "error": {"code": code, "message": message}
        }, request_id)

    async def _send_message(self, client: MobileClient, message: Dict) -> None:
        """Send message to client."""
        try:
            await client.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to {client.client_id}: {e}")

    async def broadcast_event(self, event_type: str, data: Dict) -> None:
        """Broadcast event to all subscribed clients."""
        message = {
            "type": "event",
            "event": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        for client in self._clients.values():
            if not client.authenticated:
                continue
            if not client.capabilities or event_type in client.capabilities or "*" in client.capabilities:
                await self._send_message(client, message)

    async def send_notification(self, title: str, body: str, notification_type: str = "info", target_client: Optional[str] = None) -> None:
        """Send push notification to client(s)."""
        data = {
            "title": title,
            "body": body,
            "type": notification_type,
            "timestamp": time.time(),
        }
        if target_client and target_client in self._clients:
            await self._send_message(self._clients[target_client], {"type": "notification", "data": data})
        else:
            await self.broadcast_event("notification", data)

    async def _disconnect_client(self, client_id: str) -> None:
        """Clean up client connection."""
        if client_id in self._clients:
            client = self._clients[client_id]
            try:
                await client.websocket.close()
            except Exception:
                pass
            del self._clients[client_id]
            logger.info(f"Client {client_id} disconnected")

    async def shutdown(self) -> None:
        """Shutdown the bridge."""
        self._running = False
        for client_id in list(self._clients.keys()):
            await self._disconnect_client(client_id)
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Android Bridge shutdown complete")

    def get_connected_clients(self) -> List[Dict]:
        """Get list of connected clients."""
        return [
            {
                "client_id": c.client_id,
                "authenticated": c.authenticated,
                "user_id": c.user_id,
                "device_name": c.device_name,
                "connected_at": c.connected_at.isoformat(),
                "capabilities": c.capabilities,
            }
            for c in self._clients.values()
        ]


# Global instance
_android_bridge: Optional[AndroidBridge] = None


async def get_android_bridge(config: Optional[AndroidConfig] = None) -> AndroidBridge:
    """Get or create global AndroidBridge instance."""
    global _android_bridge
    if _android_bridge is None:
        _android_bridge = AndroidBridge(config)
        await _android_bridge.initialize()
    return _android_bridge