"""
Device Manager - Central registry and control for all connected devices.
Handles authentication, permissions, and command routing.
"""
from __future__ import annotations
import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)


class DeviceType(Enum):
    """Supported device types."""
    COMPUTER = "computer"           # Windows/Linux/Mac
    ANDROID = "android"             # Android phone/tablet
    IOS = "ios"                     # iPhone/iPad
    SMART_TV = "smart_tv"           # Smart TV
    SPEAKER = "speaker"             # Bluetooth/WiFi speaker
    LIGHT = "light"                 # Smart light
    CAMERA = "camera"               # IP Camera
    ROUTER = "router"               # Router/Network device
    SENSOR = "sensor"               # IoT Sensor
    ACTUATOR = "actuator"           # Relay, switch, etc.
    HOME_ASSISTANT = "home_assistant"  # Home Assistant instance
    UNKNOWN = "unknown"


class DeviceStatus(Enum):
    """Device connection status."""
    DISCOVERED = "discovered"       # Found but not authenticated
    AUTHENTICATING = "authenticating"
    CONNECTING = "authenticating"   # alias (usado por command_center)
    CONNECTED = "connected"         # Authenticated and ready
    DISCONNECTED = "disconnected"   # Was connected, now offline
    ERROR = "error"                 # Connection error
    BLOCKED = "blocked"             # Explicitly blocked


class ConnectionProtocol(Enum):
    """Supported connection protocols."""
    ADB = "adb"                     # Android Debug Bridge
    SSH = "ssh"                     # SSH
    HTTP = "http"                   # REST API
    HTTPS = "https"                 # REST API with TLS
    MQTT = "mqtt"                   # MQTT
    WEBSOCKET = "websocket"         # WebSocket
    BLUETOOTH = "bluetooth"         # Bluetooth Classic/BLE
    ONVIF = "onvif"                 # ONVIF (cameras)
    MATTER = "matter"               # Matter/Thread
    HOME_ASSISTANT = "home_assistant"  # Home Assistant API
    CUSTOM = "custom"


@dataclass
class DeviceCapability:
    """A capability that a device supports."""
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    danger_level: int = 0  # 0=safe, 1=caution, 2=dangerous


@dataclass
class Device:
    """Represents a connected device."""
    id: str
    name: str
    type: DeviceType
    protocol: ConnectionProtocol
    address: str  # IP, MAC, ADB serial, etc.
    port: Optional[int] = None
    status: DeviceStatus = DeviceStatus.DISCOVERED
    capabilities: list[DeviceCapability] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Manufacturer, model, firmware, etc.
    auth_token: Optional[str] = None
    last_seen: Optional[datetime] = None
    registered_at: datetime = field(default_factory=datetime.now)
    trusted: bool = False
    permissions: list[str] = field(default_factory=list)  # Granted permissions

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        data = asdict(self)
        data['type'] = self.type.value
        data['protocol'] = self.protocol.value
        data['status'] = self.status.value
        data['last_seen'] = self.last_seen.isoformat() if self.last_seen else None
        data['registered_at'] = self.registered_at.isoformat()
        data['capabilities'] = [asdict(c) for c in self.capabilities]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Device':
        """Deserialize from dictionary."""
        data = data.copy()
        data['type'] = DeviceType(data['type'])
        data['protocol'] = ConnectionProtocol(data['protocol'])
        data['status'] = DeviceStatus(data['status'])
        data['last_seen'] = datetime.fromisoformat(data['last_seen']) if data.get('last_seen') else None
        data['registered_at'] = datetime.fromisoformat(data['registered_at'])
        data['capabilities'] = [DeviceCapability(**c) for c in data.get('capabilities', [])]
        return cls(**data)


class DeviceRegistry:
    """Persistent device registry with encryption support."""

    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.devices: dict[str, Device] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for device_data in data.get('devices', []):
                    device = Device.from_dict(device_data)
                    self.devices[device.id] = device
                logger.info(f"Loaded {len(self.devices)} devices from registry")
            except Exception as e:
                logger.error(f"Failed to load device registry: {e}")

    def save(self) -> None:
        """Save registry to disk."""
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'version': 1,
                'updated_at': datetime.now().isoformat(),
                'devices': [d.to_dict() for d in self.devices.values()]
            }
            with open(self.registry_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save device registry: {e}")

    def register(self, device: Device) -> None:
        """Register a new device."""
        self.devices[device.id] = device
        self.save()

    def unregister(self, device_id: str) -> bool:
        """Unregister a device."""
        if device_id in self.devices:
            del self.devices[device_id]
            self.save()
            return True
        return False

    def get(self, device_id: str) -> Optional[Device]:
        """Get device by ID."""
        return self.devices.get(device_id)

    def get_by_name(self, name: str) -> Optional[Device]:
        """Get device by name (first match)."""
        for device in self.devices.values():
            if device.name.lower() == name.lower():
                return device
        return None

    def get_by_type(self, device_type: DeviceType) -> list[Device]:
        """Get all devices of a type."""
        return [d for d in self.devices.values() if d.type == device_type]

    def get_connected(self) -> list[Device]:
        """Get all connected devices."""
        return [d for d in self.devices.values() if d.status == DeviceStatus.CONNECTED]

    def get_trusted(self) -> list[Device]:
        """Get all trusted devices."""
        return [d for d in self.devices.values() if d.trusted]

    def update_status(self, device_id: str, status: DeviceStatus) -> bool:
        """Update device status."""
        if device_id in self.devices:
            self.devices[device_id].status = status
            self.devices[device_id].last_seen = datetime.now()
            self.save()
            return True
        return False

    def update_last_seen(self, device_id: str) -> bool:
        """Update last seen timestamp."""
        if device_id in self.devices:
            self.devices[device_id].last_seen = datetime.now()
            self.save()
            return True
        return False

    def set_trusted(self, device_id: str, trusted: bool) -> bool:
        """Set device trust status."""
        if device_id in self.devices:
            self.devices[device_id].trusted = trusted
            self.save()
            return True
        return False

    def grant_permission(self, device_id: str, permission: str) -> bool:
        """Grant a permission to a device."""
        if device_id in self.devices:
            if permission not in self.devices[device_id].permissions:
                self.devices[device_id].permissions.append(permission)
                self.save()
            return True
        return False

    def revoke_permission(self, device_id: str, permission: str) -> bool:
        """Revoke a permission from a device."""
        if device_id in self.devices:
            if permission in self.devices[device_id].permissions:
                self.devices[device_id].permissions.remove(permission)
                self.save()
            return True
        return False

    def list_all(self) -> list[Device]:
        """List all registered devices."""
        return list(self.devices.values())


class DeviceManager:
    """
    Central device manager.
    Coordinates discovery, authentication, and command execution.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry = DeviceRegistry(registry_path or Path("devices/registry.json"))
        self._connection_handlers: dict[ConnectionProtocol, Callable] = {}
        self._command_handlers: dict[str, Callable] = {}
        self._event_callbacks: list[Callable] = []
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

    def register_protocol_handler(self, protocol: ConnectionProtocol, handler: Callable) -> None:
        """Register a handler for a connection protocol."""
        self._connection_handlers[protocol] = handler

    def register_command_handler(self, command: str, handler: Callable) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler

    def on_event(self, callback: Callable) -> None:
        """Register event callback."""
        self._event_callbacks.append(callback)

    def _emit_event(self, event_type: str, device: Device, data: dict = None) -> None:
        """Emit event to all callbacks."""
        event = {
            'type': event_type,
            'device_id': device.id,
            'device_name': device.name,
            'timestamp': datetime.now().isoformat(),
            'data': data or {}
        }
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    async def connect_device(self, device_id: str, auth_data: dict = None) -> bool:
        """Connect to a registered device."""
        device = self.registry.get(device_id)
        if not device:
            logger.error(f"Device not found: {device_id}")
            return False

        handler = self._connection_handlers.get(device.protocol)
        if not handler:
            logger.error(f"No handler for protocol: {device.protocol}")
            device.status = DeviceStatus.ERROR
            self.registry.save()
            return False

        try:
            device.status = DeviceStatus.AUTHENTICATING
            self.registry.save()

            success = await handler(device, auth_data or {})

            if success:
                device.status = DeviceStatus.CONNECTED
                device.last_seen = datetime.now()
                if not device.auth_token:
                    device.auth_token = str(uuid.uuid4())
                self.registry.save()
                self._emit_event('device_connected', device)
                logger.info(f"Device connected: {device.name} ({device.id})")
            else:
                device.status = DeviceStatus.ERROR
                self.registry.save()
                logger.error(f"Failed to connect to {device.name}")

            return success

        except Exception as e:
            device.status = DeviceStatus.ERROR
            self.registry.save()
            logger.error(f"Connection error for {device.name}: {e}")
            return False

    async def disconnect_device(self, device_id: str) -> bool:
        """Disconnect a device."""
        device = self.registry.get(device_id)
        if not device:
            return False

        device.status = DeviceStatus.DISCONNECTED
        self.registry.save()
        self._emit_event('device_disconnected', device)
        return True

    async def execute_command(
        self,
        device_id: str,
        command: str,
        parameters: dict = None,
        require_confirmation: bool = False
    ) -> dict:
        """Execute a command on a device."""
        device = self.registry.get(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}

        if device.status != DeviceStatus.CONNECTED:
            return {"success": False, "error": f"Device not connected (status: {device.status.value})"}

        # Check permissions
        if require_confirmation and not device.trusted:
            return {"success": False, "error": "Confirmation required for untrusted device"}

        # Check if device has the capability
        capability = next((c for c in device.capabilities if c.name == command), None)
        if not capability:
            return {"success": False, "error": f"Command '{command}' not supported by device"}

        if capability.requires_confirmation and not device.trusted:
            return {"success": False, "error": "Confirmation required"}

        handler = self._command_handlers.get(command)
        if not handler:
            return {"success": False, "error": f"No handler for command: {command}"}

        try:
            self._emit_event('command_started', device, {'command': command, 'parameters': parameters})
            result = await handler(device, parameters or {})
            self._emit_event('command_completed', device, {
                'command': command,
                'success': result.get('success', False),
                'result': result
            })
            return result
        except Exception as e:
            logger.error(f"Command error on {device.name}: {e}")
            self._emit_event('command_failed', device, {'command': command, 'error': str(e)})
            return {"success": False, "error": str(e)}

    def get_device(self, device_id: str) -> Optional[Device]:
        return self.registry.get(device_id)

    def get_device_by_name(self, name: str) -> Optional[Device]:
        return self.registry.get_by_name(name)

    def list_devices(
        self,
        device_type: Optional[DeviceType] = None,
        status: Optional[DeviceStatus] = None,
        trusted_only: bool = False
    ) -> list[Device]:
        devices = self.registry.list_all()
        if device_type:
            devices = [d for d in devices if d.type == device_type]
        if status:
            devices = [d for d in devices if d.status == status]
        if trusted_only:
            devices = [d for d in devices if d.trusted]
        return devices

    async def start_monitoring(self, interval: int = 30) -> None:
        """Start periodic device monitoring."""
        if self._monitoring:
            return
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))

    async def stop_monitoring(self) -> None:
        """Stop monitoring."""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self, interval: int) -> None:
        """Monitor device health."""
        while self._monitoring:
            try:
                for device in self.registry.get_connected():
                    # Ping/health check
                    await self._check_device_health(device)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(interval)

    async def _check_device_health(self, device: Device) -> None:
        """Check if device is still responsive."""
        # Implement protocol-specific health checks
        pass

    def register_discovered_device(
        self,
        name: str,
        device_type: DeviceType,
        protocol: ConnectionProtocol,
        address: str,
        port: Optional[int] = None,
        metadata: dict = None,
        capabilities: list[DeviceCapability] = None
    ) -> Device:
        """Register a newly discovered device."""
        device_id = str(uuid.uuid4())[:8]
        device = Device(
            id=device_id,
            name=name,
            type=device_type,
            protocol=protocol,
            address=address,
            port=port,
            metadata=metadata or {},
            capabilities=capabilities or []
        )
        self.registry.register(device)
        self._emit_event('device_discovered', device)
        return device


# Global instance
_device_manager: Optional[DeviceManager] = None


def get_device_manager(registry_path: Optional[Path] = None) -> DeviceManager:
    """Get or create global DeviceManager instance."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DeviceManager(registry_path)
    return _device_manager