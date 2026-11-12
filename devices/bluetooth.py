"""
Bluetooth Manager - GATT client for BLE device control.
Handles connections, reading/writing characteristics, notifications.
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from uuid import UUID

from .manager import Device, DeviceType, ConnectionProtocol, DeviceCapability, DeviceStatus

logger = logging.getLogger(__name__)


@dataclass
class BLECharacteristic:
    """Represents a BLE characteristic."""
    uuid: str
    handle: int
    properties: list[str]  # read, write, notify, indicate, etc.
    value: Optional[bytes] = None
    descriptors: dict = field(default_factory=dict)


@dataclass
class BLEService:
    """Represents a BLE service."""
    uuid: str
    handle: int
    characteristics: dict[str, BLECharacteristic] = field(default_factory=dict)


class BluetoothManager:
    """
    Manages Bluetooth LE connections and GATT operations.
    Provides high-level interface for reading/writing characteristics.
    """

    def __init__(self):
        self._clients: dict[str, Any] = {}  # address -> BleakClient
        self._services_cache: dict[str, dict[str, BLEService]] = {}
        self._notification_callbacks: dict[str, dict[str, Callable]] = {}  # address -> char_uuid -> callback
        self._connection_lock = asyncio.Lock()

    async def connect(self, device: Device, timeout: float = 10.0) -> bool:
        """
        Connect to a BLE device.
        Returns True if successful.
        """
        if device.protocol != ConnectionProtocol.BLUETOOTH:
            logger.error(f"Device {device.name} is not a Bluetooth device")
            return False

        address = device.address

        async with self._connection_lock:
            if address in self._clients:
                client = self._clients[address]
                if client.is_connected:
                    logger.info(f"Already connected to {address}")
                    return True
                else:
                    # Clean up stale connection
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    del self._clients[address]

            try:
                from bleak import BleakClient

                client = BleakClient(address, timeout=timeout)
                await client.connect()

                if not client.is_connected:
                    logger.error(f"Failed to connect to {address}")
                    return False

                self._clients[address] = client
                self._notification_callbacks[address] = {}

                # Discover services
                await self._discover_services(address)

                logger.info(f"Connected to BLE device: {device.name} ({address})")
                return True

            except Exception as e:
                logger.error(f"BLE connection error for {address}: {e}")
                return False

    async def disconnect(self, address: str) -> bool:
        """Disconnect from a BLE device."""
        async with self._connection_lock:
            client = self._clients.get(address)
            if client:
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting {address}: {e}")
                finally:
                    del self._clients[address]
                    if address in self._services_cache:
                        del self._services_cache[address]
                    if address in self._notification_callbacks:
                        del self._notification_callbacks[address]
                    return True
            return False

    async def _discover_services(self, address: str) -> None:
        """Discover and cache GATT services."""
        client = self._clients.get(address)
        if not client:
            return

        services = {}
        for service in client.services:
            ble_service = BLEService(uuid=str(service.uuid), handle=service.handle)
            for char in service.characteristics:
                ble_char = BLECharacteristic(
                    uuid=str(char.uuid),
                    handle=char.handle,
                    properties=list(char.properties),
                    descriptors={str(d.uuid): d.handle for d in char.descriptors}
                )
                ble_service.characteristics[str(char.uuid)] = ble_char
            services[str(service.uuid)] = ble_service

        self._services_cache[address] = services
        logger.debug(f"Discovered {len(services)} services for {address}")

    def get_services(self, address: str) -> dict[str, BLEService]:
        """Get cached services for a device."""
        return self._services_cache.get(address, {})

    def get_characteristic(self, address: str, char_uuid: str) -> Optional[BLECharacteristic]:
        """Get a specific characteristic."""
        for service in self.get_services(address).values():
            if char_uuid in service.characteristics:
                return service.characteristics[char_uuid]
        return None

    async def read_characteristic(self, address: str, char_uuid: str) -> Optional[bytes]:
        """Read a characteristic value."""
        client = self._clients.get(address)
        if not client or not client.is_connected:
            logger.error(f"Not connected to {address}")
            return None

        try:
            value = await client.read_gatt_char(char_uuid)
            # Update cache
            char = self.get_characteristic(address, char_uuid)
            if char:
                char.value = value
            return value
        except Exception as e:
            logger.error(f"Read characteristic error: {e}")
            return None

    async def write_characteristic(
        self,
        address: str,
        char_uuid: str,
        data: bytes,
        response: bool = True
    ) -> bool:
        """Write to a characteristic."""
        client = self._clients.get(address)
        if not client or not client.is_connected:
            logger.error(f"Not connected to {address}")
            return False

        try:
            await client.write_gatt_char(char_uuid, data, response=response)
            return True
        except Exception as e:
            logger.error(f"Write characteristic error: {e}")
            return False

    async def start_notify(
        self,
        address: str,
        char_uuid: str,
        callback: Callable[[bytes], None]
    ) -> bool:
        """Subscribe to characteristic notifications."""
        client = self._clients.get(address)
        if not client or not client.is_connected:
            logger.error(f"Not connected to {address}")
            return False

        char = self.get_characteristic(address, char_uuid)
        if not char or 'notify' not in char.properties:
            logger.error(f"Characteristic {char_uuid} does not support notifications")
            return False

        def notification_handler(sender, data):
            callback(data)

        try:
            await client.start_notify(char_uuid, notification_handler)
            self._notification_callbacks[address][char_uuid] = callback
            logger.debug(f"Started notifications for {char_uuid} on {address}")
            return True
        except Exception as e:
            logger.error(f"Start notify error: {e}")
            return False

    async def stop_notify(self, address: str, char_uuid: str) -> bool:
        """Stop characteristic notifications."""
        client = self._clients.get(address)
        if not client or not client.is_connected:
            return False

        try:
            await client.stop_notify(char_uuid)
            if address in self._notification_callbacks:
                self._notification_callbacks[address].pop(char_uuid, None)
            return True
        except Exception as e:
            logger.error(f"Stop notify error: {e}")
            return False

    async def read_sensor_data(self, address: str, sensor_type: str) -> Optional[dict]:
        """
        Read sensor data from known sensor types.
        Supports: heart_rate, battery, temperature, humidity, pressure, xiaomi, qingping
        """
        # Standard UUIDs
        sensor_uuids = {
            'heart_rate': '00002a37-0000-1000-8000-00805f9b34fb',
            'battery': '00002a19-0000-1000-8000-00805f9b34fb',
            'temperature': '00002a6e-0000-1000-8000-00805f9b34fb',
            'humidity': '00002a6f-0000-1000-8000-00805f9b34fb',
            'pressure': '00002a6d-0000-1000-8000-00805f9b34fb',
        }

        char_uuid = sensor_uuids.get(sensor_type.lower())
        if not char_uuid:
            logger.warning(f"Unknown sensor type: {sensor_type}")
            return None

        data = await self.read_characteristic(address, char_uuid)
        if data is None:
            return None

        # Parse based on sensor type
        return self._parse_sensor_data(sensor_type, data)

    def _parse_sensor_data(self, sensor_type: str, data: bytes) -> dict:
        """Parse raw sensor data."""
        result = {'raw': data.hex()}

        try:
            if sensor_type == 'heart_rate':
                # Heart rate measurement format
                flags = data[0]
                hr_format = flags & 0x01
                if hr_format == 0:
                    # UINT8
                    result['heart_rate'] = data[1]
                else:
                    # UINT16
                    result['heart_rate'] = int.from_bytes(data[1:3], 'little')

            elif sensor_type == 'battery':
                # Battery level 0-100%
                result['battery_level'] = data[0]

            elif sensor_type in ('temperature', 'humidity', 'pressure'):
                # IEEE 11073 FLOAT (16-bit exponent, 24-bit mantissa) or simple int16/uint16
                if len(data) >= 2:
                    # Try as int16 (common for temperature * 100)
                    value = int.from_bytes(data[:2], 'little', signed=True)
                    if sensor_type == 'temperature':
                        result['temperature_c'] = value / 100.0
                    elif sensor_type == 'humidity':
                        result['humidity_percent'] = value / 100.0
                    elif sensor_type == 'pressure':
                        result['pressure_hpa'] = value / 10.0

        except Exception as e:
            logger.error(f"Parse sensor data error: {e}")

        return result

    async def write_xiaomi_config(self, address: str, config: dict) -> bool:
        """Write configuration to Xiaomi BLE devices."""
        # Xiaomi uses specific UUIDs and encryption
        # This is a simplified version - real implementation needs auth
        xiaomi_uuids = {
            'write': '0000fff1-0000-1000-8000-00805f9b34fb',
            'notify': '0000fff2-0000-1000-8000-00805f9b34fb',
        }

        # Would need proper Xiaomi encryption protocol
        logger.warning("Xiaomi config write not fully implemented")
        return False

    def is_connected(self, address: str) -> bool:
        """Check if connected to device."""
        client = self._clients.get(address)
        return client is not None and client.is_connected

    async def disconnect_all(self) -> None:
        """Disconnect all devices."""
        addresses = list(self._clients.keys())
        for address in addresses:
            await self.disconnect(address)


# Global instance
_bluetooth_manager: Optional[BluetoothManager] = None


def get_bluetooth_manager() -> BluetoothManager:
    """Get or create global BluetoothManager instance."""
    global _bluetooth_manager
    if _bluetooth_manager is None:
        _bluetooth_manager = BluetoothManager()
    return _bluetooth_manager


# High-level async functions for tool integration
async def ble_connect(address: str, timeout: float = 10.0) -> dict:
    """Connect to BLE device by address."""
    from .manager import get_device_manager, Device, DeviceType, ConnectionProtocol, DeviceStatus

    # Find or create device
    dm = get_device_manager()
    device = None
    for d in dm.registry.list_all():
        if d.address == address and d.protocol == ConnectionProtocol.BLUETOOTH:
            device = d
            break

    if not device:
        device = Device(
            id=address.replace(':', ''),
            name=f"BLE-{address[-6:]}",
            type=DeviceType.SENSOR,
            protocol=ConnectionProtocol.BLUETOOTH,
            address=address,
            status=DeviceStatus.DISCOVERED
        )
        dm.registry.register(device)

    manager = get_bluetooth_manager()
    success = await manager.connect(device, timeout)

    return {"success": success, "address": address}


async def ble_read(address: str, characteristic_uuid: str) -> dict:
    """Read a BLE characteristic."""
    manager = get_bluetooth_manager()
    value = await manager.read_characteristic(address, characteristic_uuid)

    if value is None:
        return {"success": False, "error": "Read failed"}

    return {
        "success": True,
        "address": address,
        "characteristic": characteristic_uuid,
        "value": value.hex(),
        "value_ascii": value.decode('utf-8', errors='ignore')
    }


async def ble_write(address: str, characteristic_uuid: str, data_hex: str, response: bool = True) -> dict:
    """Write to a BLE characteristic."""
    manager = get_bluetooth_manager()
    try:
        data = bytes.fromhex(data_hex)
    except ValueError:
        return {"success": False, "error": "Invalid hex data"}

    success = await manager.write_characteristic(address, characteristic_uuid, data, response)
    return {"success": success, "address": address, "characteristic": characteristic_uuid}


async def ble_notify(address: str, characteristic_uuid: str, enable: bool) -> dict:
    """Enable/disable BLE notifications."""
    manager = get_bluetooth_manager()

    if enable:
        # Need a callback - for now just return status
        return {"success": False, "error": "Notifications require callback registration via API"}
    else:
        success = await manager.stop_notify(address, characteristic_uuid)
        return {"success": success, "address": address, "characteristic": characteristic_uuid}


async def ble_read_sensor(address: str, sensor_type: str) -> dict:
    """Read sensor data from BLE device."""
    manager = get_bluetooth_manager()
    data = await manager.read_sensor_data(address, sensor_type)

    if data is None:
        return {"success": False, "error": "Failed to read sensor"}

    return {"success": True, "address": address, "sensor": sensor_type, "data": data}


async def ble_discover_services(address: str) -> dict:
    """Discover and list all GATT services."""
    manager = get_bluetooth_manager()
    services = manager.get_services(address)

    result = {}
    for uuid, service in services.items():
        result[uuid] = {
            "handle": service.handle,
            "characteristics": {
                cuuid: {
                    "handle": char.handle,
                    "properties": char.properties,
                    "descriptors": char.descriptors
                }
                for cuuid, char in service.characteristics.items()
            }
        }

    return {"success": True, "address": address, "services": result}