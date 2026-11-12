"""
Compatibilidade: módulos antigos importam de `devices.device_registry`.
O registro real vive em `devices.manager`.
"""
from devices.manager import (  # noqa: F401
    ConnectionProtocol,
    Device,
    DeviceCapability,
    DeviceManager,
    DeviceRegistry,
    DeviceStatus,
    DeviceType,
    get_device_manager,
)

ConnectionStatus = DeviceStatus
