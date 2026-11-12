"""
Secure Device Registry - Encrypted device registry with access control for JARVIS.
Extends the base device registry with encryption and audit capabilities.
"""
from __future__ import annotations
import json
import logging
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from devices.manager import Device, DeviceType, DeviceStatus, ConnectionProtocol, DeviceCapability

logger = logging.getLogger(__name__)


@dataclass
class SecureDevice(Device):
    """Device with additional security fields."""
    # Inherited: id, name, type, protocol, address, port, status, capabilities, metadata
    # auth_token, last_seen, registered_at, trusted, permissions

    # Security extensions
    encryption_key_id: Optional[str] = None  # Reference to stored encryption key
    allowed_users: List[str] = field(default_factory=list)  # Empty = all
    allowed_networks: List[str] = field(default_factory=list)  # CIDR ranges
    max_command_rate: int = 60  # commands per minute
    command_count: int = 0
    last_command_at: Optional[datetime] = None
    blocked: bool = False
    block_reason: str = ""
    security_level: int = 1  # 1=low, 2=medium, 3=high, 4=critical
    requires_mfa: bool = False  # Multi-factor auth for commands
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class SecureDeviceRegistry:
    """
    Encrypted device registry with access control.
    """

    def __init__(self, registry_path: Path, master_key: bytes = None):
        self.registry_path = registry_path
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Encryption
        key_path = registry_path.with_suffix(".key")
        if master_key:
            self._master_key = master_key
        elif key_path.exists():
            self._master_key = key_path.read_bytes()
        else:
            self._master_key = Fernet.generate_key()
            key_path.write_bytes(self._master_key)

        self._fernet = Fernet(self._master_key)
        self._devices: Dict[str, SecureDevice] = {}
        self._access_log: List[Dict] = []
        self._load()

    def _encrypt_data(self, data: str) -> str:
        return self._fernet.encrypt(data.encode()).decode()

    def _decrypt_data(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode()).decode()

    def _load(self) -> None:
        """Load registry from encrypted storage."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    encrypted_data = f.read()

                decrypted = self._decrypt_data(encrypted_data)
                data = json.loads(decrypted)

                for device_data in data.get("devices", []):
                    # Handle both old and new format
                    if "encryption_key_id" in device_data:
                        device = SecureDevice(**device_data)
                    else:
                        # Convert old format
                        base_device = Device.from_dict(device_data)
                        device = SecureDevice(
                            id=base_device.id,
                            name=base_device.name,
                            type=base_device.type,
                            protocol=base_device.protocol,
                            address=base_device.address,
                            port=base_device.port,
                            status=base_device.status,
                            capabilities=base_device.capabilities,
                            metadata=base_device.metadata,
                            auth_token=base_device.auth_token,
                            last_seen=base_device.last_seen,
                            registered_at=base_device.registered_at,
                            trusted=base_device.trusted,
                            permissions=base_device.permissions
                        )
                    self._devices[device.id] = device

                self._access_log = data.get("access_log", [])
                logger.info(f"Loaded {len(self._devices)} devices from secure registry")
            except Exception as e:
                logger.error(f"Failed to load secure device registry: {e}")

    def _save(self) -> None:
        """Save registry to encrypted storage."""
        try:
            data = {
                "version": 2,
                "updated_at": datetime.now().isoformat(),
                "devices": [self._device_to_dict(d) for d in self._devices.values()],
                "access_log": self._access_log[-1000:]  # Keep last 1000 entries
            }

            json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
            encrypted = self._encrypt_data(json_str)

            with open(self.registry_path, "w", encoding="utf-8") as f:
                f.write(encrypted)
        except Exception as e:
            logger.error(f"Failed to save secure device registry: {e}")

    def _device_to_dict(self, device: SecureDevice) -> Dict:
        """Convert SecureDevice to dict for serialization."""
        base_dict = device.to_dict()
        base_dict.update({
            "encryption_key_id": device.encryption_key_id,
            "allowed_users": device.allowed_users,
            "allowed_networks": device.allowed_networks,
            "max_command_rate": device.max_command_rate,
            "command_count": device.command_count,
            "last_command_at": device.last_command_at.isoformat() if device.last_command_at else None,
            "blocked": device.blocked,
            "block_reason": device.block_reason,
            "security_level": device.security_level,
            "requires_mfa": device.requires_mfa,
            "approved_by": device.approved_by,
            "approved_at": device.approved_at.isoformat() if device.approved_at else None
        })
        return base_dict

    def register(self, device: SecureDevice) -> None:
        """Register a new device."""
        self._devices[device.id] = device
        self._log_access("register", device.id, {"name": device.name, "type": device.type.value})
        self._save()

    def unregister(self, device_id: str) -> bool:
        """Unregister a device."""
        if device_id in self._devices:
            del self._devices[device_id]
            self._log_access("unregister", device_id, {})
            self._save()
            return True
        return False

    def get(self, device_id: str) -> Optional[SecureDevice]:
        """Get device by ID."""
        return self._devices.get(device_id)

    def get_by_name(self, name: str) -> Optional[SecureDevice]:
        """Get device by name."""
        for device in self._devices.values():
            if device.name.lower() == name.lower():
                return device
        return None

    def list_all(self, user: str = None, network: str = None) -> List[SecureDevice]:
        """List devices accessible to user/network."""
        devices = list(self._devices.values())

        if user:
            devices = [d for d in devices if not d.allowed_users or user in d.allowed_users]

        if network:
            devices = [d for d in devices if not d.allowed_networks or self._network_matches(network, d.allowed_networks)]

        return devices

    def _network_matches(self, network: str, allowed: List[str]) -> bool:
        """Check if network matches allowed CIDR ranges."""
        import ipaddress
        try:
            net = ipaddress.ip_network(network, strict=False)
            for allowed_range in allowed:
                if net.subnet_of(ipaddress.ip_network(allowed_range, strict=False)):
                    return True
        except Exception:
            pass
        return False

    def update_status(self, device_id: str, status: DeviceStatus, user: str = None) -> bool:
        """Update device status."""
        device = self._devices.get(device_id)
        if device:
            device.status = status
            device.last_seen = datetime.now()
            self._log_access("status_change", device_id, {"status": status.value}, user)
            self._save()
            return True
        return False

    def check_command_rate(self, device_id: str) -> bool:
        """Check if device is within command rate limit."""
        device = self._devices.get(device_id)
        if not device:
            return False

        now = datetime.now()
        if device.last_command_at:
            # Reset count if more than a minute passed
            if (now - device.last_command_at).total_seconds() > 60:
                device.command_count = 0

        if device.command_count >= device.max_command_rate:
            return False

        device.command_count += 1
        device.last_command_at = now
        return True

    def set_trusted(self, device_id: str, trusted: bool, approved_by: str = None) -> bool:
        """Set device trust status with approval tracking."""
        device = self._devices.get(device_id)
        if device:
            device.trusted = trusted
            if trusted:
                device.approved_by = approved_by
                device.approved_at = datetime.now()
            else:
                device.approved_by = None
                device.approved_at = None
            self._log_access("trust_change", device_id, {"trusted": trusted}, approved_by)
            self._save()
            return True
        return False

    def block_device(self, device_id: str, reason: str, blocked_by: str = None) -> bool:
        """Block a device."""
        device = self._devices.get(device_id)
        if device:
            device.blocked = True
            device.block_reason = reason
            self._log_access("block", device_id, {"reason": reason}, blocked_by)
            self._save()
            return True
        return False

    def unblock_device(self, device_id: str, unblocked_by: str = None) -> bool:
        """Unblock a device."""
        device = self._devices.get(device_id)
        if device:
            device.blocked = False
            device.block_reason = ""
            self._log_access("unblock", device_id, {}, unblocked_by)
            self._save()
            return True
        return False

    def grant_permission(self, device_id: str, permission: str) -> bool:
        """Grant permission to device."""
        device = self._devices.get(device_id)
        if device and permission not in device.permissions:
            device.permissions.append(permission)
            self._save()
            return True
        return False

    def revoke_permission(self, device_id: str, permission: str) -> bool:
        """Revoke permission from device."""
        device = self._devices.get(device_id)
        if device and permission in device.permissions:
            device.permissions.remove(permission)
            self._save()
            return True
        return False

    def _log_access(self, action: str, device_id: str, details: Dict, user: str = None) -> None:
        """Log access to audit trail."""
        self._access_log.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "device_id": device_id,
            "user": user or "system",
            "details": details
        })

    def get_access_log(self, device_id: str = None, limit: int = 100) -> List[Dict]:
        """Get access log."""
        log = self._access_log
        if device_id:
            log = [e for e in log if e["device_id"] == device_id]
        return log[-limit:]

    def export_devices(self, include_secrets: bool = False) -> List[Dict]:
        """Export devices for backup."""
        result = []
        for device in self._devices.values():
            d = self._device_to_dict(device)
            if not include_secrets:
                d.pop("auth_token", None)
                d.pop("encryption_key_id", None)
            result.append(d)
        return result

    def import_devices(self, devices: List[Dict], overwrite: bool = False) -> int:
        """Import devices from backup."""
        count = 0
        for d in devices:
            device_id = d.get("id")
            if device_id in self._devices and not overwrite:
                continue

            # Convert to SecureDevice
            device = SecureDevice(**d)
            self._devices[device.id] = device
            count += 1

        if count > 0:
            self._save()
        return count


# Global instance
_secure_device_registry: Optional[SecureDeviceRegistry] = None


def get_secure_device_registry(registry_path: Path = None, master_key: bytes = None) -> SecureDeviceRegistry:
    """Get or create global SecureDeviceRegistry."""
    global _secure_device_registry
    if _secure_device_registry is None:
        _secure_device_registry = SecureDeviceRegistry(
            registry_path or Path("security/devices_secure.json"),
            master_key
        )
    return _secure_device_registry


# High-level async functions for tool integration
async def secure_device_register(
    name: str,
    device_type: str,
    protocol: str,
    address: str,
    port: int = None,
    metadata: dict = None,
    capabilities: list = None,
    allowed_users: list = None,
    allowed_networks: list = None,
    security_level: int = 1,
    requires_mfa: bool = False
) -> dict:
    """Register a device in secure registry."""
    from devices.manager import DeviceType, ConnectionProtocol, DeviceCapability

    registry = get_secure_device_registry()

    dtype = DeviceType(device_type)
    proto = ConnectionProtocol(protocol)

    caps = []
    if capabilities:
        for cap in capabilities:
            caps.append(DeviceCapability(**cap))

    device = SecureDevice(
        id=secrets.token_hex(8),
        name=name,
        type=dtype,
        protocol=proto,
        address=address,
        port=port,
        metadata=metadata or {},
        capabilities=caps,
        allowed_users=allowed_users or [],
        allowed_networks=allowed_networks or [],
        security_level=security_level,
        requires_mfa=requires_mfa
    )

    registry.register(device)
    return {"success": True, "device": device.to_dict()}


async def secure_device_list(user: str = None, network: str = None) -> dict:
    """List devices from secure registry."""
    registry = get_secure_device_registry()
    devices = registry.list_all(user, network)
    return {"success": True, "devices": [d.to_dict() for d in devices]}


async def secure_device_get(device_id: str) -> dict:
    """Get device from secure registry."""
    registry = get_secure_device_registry()
    device = registry.get(device_id)
    if device:
        return {"success": True, "device": device.to_dict()}
    return {"success": False, "error": "Device not found"}


async def secure_device_block(device_id: str, reason: str, blocked_by: str = None) -> dict:
    """Block a device."""
    registry = get_secure_device_registry()
    success = registry.block_device(device_id, reason, blocked_by)
    return {"success": success}


async def secure_device_unblock(device_id: str, unblocked_by: str = None) -> dict:
    """Unblock a device."""
    registry = get_secure_device_registry()
    success = registry.unblock_device(device_id, unblocked_by)
    return {"success": success}


async def secure_device_set_trusted(device_id: str, trusted: bool, approved_by: str = None) -> dict:
    """Set device trust status."""
    registry = get_secure_device_registry()
    success = registry.set_trusted(device_id, trusted, approved_by)
    return {"success": success}


async def secure_device_access_log(device_id: str = None, limit: int = 100) -> dict:
    """Get device access log."""
    registry = get_secure_device_registry()
    log = registry.get_access_log(device_id, limit)
    return {"success": True, "log": log}