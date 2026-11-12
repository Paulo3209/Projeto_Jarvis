"""
Device Network Manager - Central management for distributed JARVIS agents.
Coordinates agents across computers, phones, TVs, and IoT devices.
"""
from __future__ import annotations
import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path

from core.event_bus import EventBus, EventType, get_event_bus
from security.authentication import get_jwt_manager, get_api_key_manager

logger = logging.getLogger(__name__)


class DeviceRole(Enum):
    """Roles in the device network."""
    CONTROLLER = "controller"      # Main JARVIS instance
    AGENT = "agent"                # Installed agent on other devices
    CLIENT = "client"              # Mobile app, remote control
    SENSOR = "sensor"              # IoT sensors
    DISPLAY = "display"            # TVs, displays


class DeviceStatus(Enum):
    """Device connection status."""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    UPDATING = "updating"


@dataclass
class NetworkConfig:
    """Network configuration."""
    controller_id: str = ""
    listen_host: str = "0.0.0.0"
    listen_port: int = 8766
    discovery_port: int = 5353
    heartbeat_interval: int = 10
    sync_interval: int = 5
    max_agents: int = 50
    auto_approve_trusted: bool = True
    encryption_enabled: bool = True
    jwt_secret: Optional[str] = None


@dataclass
class NetworkDevice:
    """Device in the network."""
    device_id: str
    name: str
    role: DeviceRole
    device_type: str  # computer, phone, tv, iot, etc.
    platform: str     # windows, linux, android, ios, etc.
    capabilities: List[str] = field(default_factory=list)
    status: DeviceStatus = DeviceStatus.OFFLINE
    address: str = ""  # IP or hostname
    port: int = 0
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)
    trusted: bool = False
    public_key: Optional[str] = None
    assigned_tasks: List[str] = field(default_factory=list)


class DeviceNetworkManager:
    """
    Manages the distributed device network.
    Handles discovery, registration, communication, and task distribution.
    """

    def __init__(self, config: Optional[NetworkConfig] = None):
        self.config = config or NetworkConfig()
        if not self.config.controller_id:
            self.config.controller_id = f"jarvis-{secrets.token_hex(4)}"

        self._devices: Dict[str, NetworkDevice] = {}
        self._connections: Dict[str, Any] = {}  # websocket connections
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._event_bus: Optional[EventBus] = None
        self._jwt_manager = get_jwt_manager()
        self._api_key_manager = get_api_key_manager()
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._task_results: Dict[str, asyncio.Future] = {}
        self._message_handlers: Dict[str, Callable] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register message handlers."""
        self._message_handlers = {
            "register": self._handle_register,
            "heartbeat": self._handle_heartbeat,
            "task_request": self._handle_task_request,
            "task_result": self._handle_task_result,
            "event": self._handle_event,
            "sync_request": self._handle_sync_request,
            "command": self._handle_command,
            "get_devices": self._handle_get_devices,
        }

    async def initialize(self) -> None:
        """Initialize network manager."""
        self._event_bus = await get_event_bus()
        await self._start_server()
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._task_processor())
        logger.info(f"Device Network started as {self.config.controller_id} on port {self.config.listen_port}")

    async def _start_server(self) -> None:
        """Start WebSocket server for agent connections."""
        import websockets

        async def handler(websocket, path):
            peer = websocket.remote_address
            logger.info(f"New connection from {peer}")
            try:
                async for message in websocket:
                    await self._process_message(websocket, message)
            except Exception as e:
                logger.error(f"Connection error: {e}")
            finally:
                await self._cleanup_connection(websocket)

        self._server = await websockets.serve(
            handler,
            self.config.listen_host,
            self.config.listen_port,
            max_size=10 * 1024 * 1024,
            ping_interval=self.config.heartbeat_interval,
            ping_timeout=5,
        )
        self._running = True

    async def _process_message(self, websocket, message: str) -> None:
        """Process incoming message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            handler = self._message_handlers.get(msg_type)
            if handler:
                await handler(websocket, data)
            else:
                await self._send_error(websocket, "unknown_type", f"Unknown message type: {msg_type}")
        except json.JSONDecodeError:
            await self._send_error(websocket, "invalid_json", "Invalid JSON")
        except Exception as e:
            logger.error(f"Message processing error: {e}")
            await self._send_error(websocket, "error", str(e))

    async def _handle_register(self, websocket, data: Dict) -> None:
        """Handle device registration."""
        device_id = data.get("device_id") or f"dev-{secrets.token_hex(4)}"
        name = data.get("name", f"Device-{device_id[:8]}")
        role = DeviceRole(data.get("role", "agent"))
        device_type = data.get("device_type", "unknown")
        platform = data.get("platform", "unknown")
        capabilities = data.get("capabilities", [])
        public_key = data.get("public_key")
        auth_token = data.get("auth_token")

        # Verify authentication if required
        if auth_token:
            result = await self._jwt_manager.verify_token(auth_token)
            if not result.get("success"):
                await self._send_error(websocket, "auth_failed", "Invalid auth token")
                return

        # Check if device exists and update or create
        if device_id in self._devices:
            device = self._devices[device_id]
            device.name = name
            device.role = role
            device.device_type = device_type
            device.platform = platform
            device.capabilities = capabilities
            device.public_key = public_key
            device.address = websocket.remote_address[0]
            device.status = DeviceStatus.ONLINE
            device.last_seen = datetime.now()
        else:
            device = NetworkDevice(
                device_id=device_id,
                name=name,
                role=role,
                device_type=device_type,
                platform=platform,
                capabilities=capabilities,
                public_key=public_key,
                address=websocket.remote_address[0],
                status=DeviceStatus.ONLINE,
            )
            self._devices[device_id] = device

        # Store connection
        self._connections[device_id] = websocket

        # Send registration response
        await self._send_message(websocket, {
            "type": "register_response",
            "success": True,
            "device_id": device_id,
            "controller_id": self.config.controller_id,
            "config": {
                "heartbeat_interval": self.config.heartbeat_interval,
                "sync_interval": self.config.sync_interval,
            }
        })

        # Notify event bus
        if self._event_bus:
            from core.event_bus import DeviceConnectedEvent
            self._event_bus.emit(DeviceConnectedEvent(
                device_id=device_id,
                device_info=device.__dict__,
                source="device_network"
            ))

        logger.info(f"Device registered: {device_id} ({name}) as {role.value}")

    async def _handle_heartbeat(self, websocket, data: Dict) -> None:
        """Handle heartbeat from device."""
        device_id = data.get("device_id")
        if device_id in self._devices:
            device = self._devices[device_id]
            device.last_seen = datetime.now()
            device.status = DeviceStatus(data.get("status", "online"))
            device.assigned_tasks = data.get("assigned_tasks", [])

            # Update capabilities if provided
            if "capabilities" in data:
                device.capabilities = data["capabilities"]

            await self._send_message(websocket, {
                "type": "heartbeat_ack",
                "timestamp": time.time(),
                "pending_tasks": await self._get_pending_tasks(device_id)
            })

    async def _handle_task_request(self, websocket, data: Dict) -> None:
        """Handle task request from agent."""
        device_id = data.get("device_id")
        task_type = data.get("task_type")
        payload = data.get("payload", {})

        # Queue task for processing
        task_id = secrets.token_hex(8)
        await self._task_queue.put({
            "task_id": task_id,
            "device_id": device_id,
            "task_type": task_type,
            "payload": payload,
            "request_id": data.get("request_id"),
        })

    async def _handle_task_result(self, websocket, data: Dict) -> None:
        """Handle task result from agent."""
        task_id = data.get("task_id")
        if task_id in self._task_results:
            future = self._task_results.pop(task_id)
            if not future.done():
                future.set_result(data.get("result"))

    async def _handle_event(self, websocket, data: Dict) -> None:
        """Handle event from agent."""
        if self._event_bus:
            from core.event_bus import Event
            event = Event(
                type=data.get("event_type"),
                data=data.get("data", {}),
                source=f"device:{data.get('device_id')}"
            )
            self._event_bus.emit(event)

    async def _handle_sync_request(self, websocket, data: Dict) -> None:
        """Handle state sync request."""
        device_id = data.get("device_id")
        await self._send_message(websocket, {
            "type": "sync_response",
            "devices": {k: v.__dict__ for k, v in self._devices.items()},
            "timestamp": time.time(),
        })

    async def _handle_command(self, websocket, data: Dict) -> None:
        """Handle command from controller/client."""
        # Route to appropriate device
        target_id = data.get("target_device")
        if target_id in self._connections:
            await self._send_message(self._connections[target_id], {
                "type": "command",
                "command": data.get("command"),
                "params": data.get("params", {}),
                "request_id": data.get("request_id"),
            })

    async def _handle_get_devices(self, websocket, data: Dict) -> None:
        """Handle device list request."""
        await self._send_message(websocket, {
            "type": "devices_list",
            "devices": [
                {
                    "device_id": d.device_id,
                    "name": d.name,
                    "role": d.role.value,
                    "device_type": d.device_type,
                    "platform": d.platform,
                    "status": d.status.value,
                    "capabilities": d.capabilities,
                    "trusted": d.trusted,
                }
                for d in self._devices.values()
            ]
        })

    async def _get_pending_tasks(self, device_id: str) -> List[Dict]:
        """Get pending tasks for a device."""
        # This would check a task queue for the device
        return []

    async def _send_message(self, websocket, message: Dict) -> None:
        """Send message to websocket."""
        try:
            await websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Send error: {e}")

    async def _send_error(self, websocket, code: str, message: str) -> None:
        """Send error response."""
        await self._send_message(websocket, {
            "type": "error",
            "error": {"code": code, "message": message}
        })

    async def _cleanup_connection(self, websocket) -> None:
        """Clean up disconnected connection."""
        for device_id, ws in list(self._connections.items()):
            if ws == websocket:
                if device_id in self._devices:
                    self._devices[device_id].status = DeviceStatus.OFFLINE
                del self._connections[device_id]
                logger.info(f"Device disconnected: {device_id}")
                break

    async def _heartbeat_loop(self) -> None:
        """Send heartbeats to all connected devices."""
        while self._running:
            await asyncio.sleep(self.config.heartbeat_interval)
            for device_id, websocket in list(self._connections.items()):
                try:
                    await self._send_message(websocket, {
                        "type": "heartbeat",
                        "timestamp": time.time(),
                        "controller_id": self.config.controller_id,
                    })
                except Exception:
                    await self._cleanup_connection(websocket)

    async def _task_processor(self) -> None:
        """Process queued tasks."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
                # Process task - would route to appropriate handler
                logger.info(f"Processing task {task['task_id']} for {task['device_id']}")
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Task processor error: {e}")

    # Public API
    def register_device(self, device: NetworkDevice) -> None:
        """Manually register a device."""
        self._devices[device.device_id] = device

    def get_device(self, device_id: str) -> Optional[NetworkDevice]:
        """Get device by ID."""
        return self._devices.get(device_id)

    def list_devices(self, role: DeviceRole = None, status: DeviceStatus = None) -> List[NetworkDevice]:
        """List devices with optional filters."""
        devices = list(self._devices.values())
        if role:
            devices = [d for d in devices if d.role == role]
        if status:
            devices = [d for d in devices if d.status == status]
        return devices

    def get_online_agents(self) -> List[NetworkDevice]:
        """Get all online agents."""
        return [d for d in self._devices.values()
                if d.role == DeviceRole.AGENT and d.status == DeviceStatus.ONLINE]

    async def send_command(self, device_id: str, command: str, params: Dict = None) -> Dict:
        """Send command to specific device."""
        if device_id not in self._connections:
            return {"success": False, "error": "Device not connected"}

        request_id = secrets.token_hex(8)
        future = asyncio.Future()
        self._task_results[request_id] = future

        await self._send_message(self._connections[device_id], {
            "type": "command",
            "command": command,
            "params": params or {},
            "request_id": request_id,
        })

        try:
            result = await asyncio.wait_for(future, timeout=30)
            return {"success": True, "result": result}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timeout"}
        finally:
            self._task_results.pop(request_id, None)

    async def broadcast_command(self, command: str, params: Dict = None, role: DeviceRole = None) -> Dict:
        """Broadcast command to all devices of a role."""
        targets = [d.device_id for d in self._devices.values()
                   if d.status == DeviceStatus.ONLINE and (role is None or d.role == role)]

        results = {}
        for device_id in targets:
            results[device_id] = await self.send_command(device_id, command, params)

        return {"success": True, "results": results}

    async def shutdown(self) -> None:
        """Shutdown network manager."""
        self._running = False
        for ws in self._connections.values():
            try:
                await ws.close()
            except Exception:
                pass
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Device Network shutdown complete")


# Global instance
_device_network: Optional[DeviceNetworkManager] = None


async def get_device_network(config: Optional[NetworkConfig] = None) -> DeviceNetworkManager:
    """Get global device network manager."""
    global _device_network
    if _device_network is None:
        _device_network = DeviceNetworkManager(config)
        await _device_network.initialize()
    return _device_network