"""
Device Discovery - Network and Bluetooth device discovery.
Uses zeroconf for mDNS/Bonjour and bleak for Bluetooth LE.
"""
from __future__ import annotations
import asyncio
import socket
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
from ipaddress import IPv4Network, IPv4Address

from .manager import Device, DeviceType, DeviceStatus, ConnectionProtocol, DeviceCapability, get_device_manager

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    """A device found during discovery."""
    name: str
    device_type: DeviceType
    protocol: ConnectionProtocol
    address: str
    port: Optional[int] = None
    metadata: dict = field(default_factory=dict)
    capabilities: list[DeviceCapability] = field(default_factory=list)
    rssi: Optional[int] = None  # For Bluetooth
    service_type: Optional[str] = None  # For mDNS


class BaseScanner(ABC):
    """Base class for device scanners."""

    def __init__(self, callback: Optional[Callable[[DiscoveredDevice], None]] = None):
        self.callback = callback
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @abstractmethod
    async def start(self) -> None:
        """Start scanning."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop scanning."""
        pass

    def _notify(self, device: DiscoveredDevice) -> None:
        """Notify callback of discovered device."""
        if self.callback:
            try:
                self.callback(device)
            except Exception as e:
                logger.error(f"Discovery callback error: {e}")


class NetworkScanner(BaseScanner):
    """
    Network device scanner using mDNS/Bonjour (zeroconf) and port scanning.
    Discovers: Smart TVs, speakers, cameras, routers, Home Assistant, etc.
    """

    def __init__(
        self,
        callback: Optional[Callable[[DiscoveredDevice], None]] = None,
        scan_interval: int = 60,
        network_range: Optional[str] = None
    ):
        super().__init__(callback)
        self.scan_interval = scan_interval
        self.network_range = network_range
        self._zeroconf = None
        self._browser = None
        self._known_services = {
            # mDNS service types to device type mapping
            "_googlecast._tcp.local.": (DeviceType.SMART_TV, ConnectionProtocol.HTTP),
            "_airplay._tcp.local.": (DeviceType.SPEAKER, ConnectionProtocol.HTTP),
            "_raop._tcp.local.": (DeviceType.SPEAKER, ConnectionProtocol.HTTP),
            "_spotify-connect._tcp.local.": (DeviceType.SPEAKER, ConnectionProtocol.HTTP),
            "_sonos._tcp.local.": (DeviceType.SPEAKER, ConnectionProtocol.HTTP),
            "_hue._tcp.local.": (DeviceType.LIGHT, ConnectionProtocol.HTTP),
            "_homekit._tcp.local.": (DeviceType.HOME_ASSISTANT, ConnectionProtocol.HOME_ASSISTANT),
            "_home-assistant._tcp.local.": (DeviceType.HOME_ASSISTANT, ConnectionProtocol.HOME_ASSISTANT),
            "_mqtt._tcp.local.": (DeviceType.ROUTER, ConnectionProtocol.MQTT),
            "_onvif._tcp.local.": (DeviceType.CAMERA, ConnectionProtocol.ONVIF),
            "_axis-video._tcp.local.": (DeviceType.CAMERA, ConnectionProtocol.ONVIF),
            "_dahua._tcp.local.": (DeviceType.CAMERA, ConnectionProtocol.ONVIF),
            "_hikvision._tcp.local.": (DeviceType.CAMERA, ConnectionProtocol.ONVIF),
            "_ssh._tcp.local.": (DeviceType.COMPUTER, ConnectionProtocol.SSH),
            "_http._tcp.local.": (DeviceType.UNKNOWN, ConnectionProtocol.HTTP),
            "_https._tcp.local.": (DeviceType.UNKNOWN, ConnectionProtocol.HTTPS),
            "_adb-tls._tcp.local.": (DeviceType.ANDROID, ConnectionProtocol.ADB),
        }

    async def start(self) -> None:
        """Start mDNS discovery and periodic network scan."""
        if self._running:
            return

        self._running = True

        # Start zeroconf browser
        await self._start_zeroconf()

        # Start periodic network scan
        self._task = asyncio.create_task(self._scan_loop())

        logger.info("NetworkScanner started")

    async def stop(self) -> None:
        """Stop scanning."""
        self._running = False

        if self._browser:
            self._browser.cancel()
            self._browser = None

        if self._zeroconf:
            await self._zeroconf.async_close()
            self._zeroconf = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("NetworkScanner stopped")

    async def _start_zeroconf(self) -> None:
        """Initialize zeroconf for mDNS discovery."""
        try:
            from zeroconf import AsyncZeroconf, AsyncServiceBrowser, ServiceStateChange
            from zeroconf.asyncio import AsyncServiceInfo

            self._zeroconf = AsyncZeroconf()

            # Browse for all relevant service types
            service_types = list(self._known_services.keys())

            def on_service_state_change(zeroconf, service_type: str, name: str, state_change: ServiceStateChange):
                if state_change == ServiceStateChange.Added:
                    asyncio.create_task(self._resolve_service(service_type, name))

            self._browser = AsyncServiceBrowser(
                self._zeroconf.zeroconf,
                service_types,
                handlers=[on_service_state_change]
            )

            logger.info(f"Zeroconf browser started for {len(service_types)} service types")

        except ImportError:
            logger.warning("zeroconf not available, mDNS discovery disabled")
        except Exception as e:
            logger.error(f"Failed to start zeroconf: {e}")

    async def _resolve_service(self, service_type: str, name: str) -> None:
        """Resolve service details."""
        if not self._zeroconf:
            return

        try:
            from zeroconf.asyncio import AsyncServiceInfo

            info = AsyncServiceInfo(service_type, name)
            await info.async_request(self._zeroconf, 3000)

            if info.addresses:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port or 80

                # Determine device type and protocol
                device_type, protocol = self._known_services.get(service_type, (DeviceType.UNKNOWN, ConnectionProtocol.HTTP))

                # Extract metadata from TXT records
                metadata = {}
                if info.properties:
                    for k, v in info.properties.items():
                        try:
                            metadata[k.decode() if isinstance(k, bytes) else k] = \
                                v.decode() if isinstance(v, bytes) else v
                        except Exception:
                            pass

                # Clean name
                clean_name = name.replace(f".{service_type}", "").replace("\\", "")

                device = DiscoveredDevice(
                    name=clean_name,
                    device_type=device_type,
                    protocol=protocol,
                    address=address,
                    port=port,
                    metadata=metadata,
                    service_type=service_type
                )

                self._notify(device)

        except Exception as e:
            logger.debug(f"Failed to resolve service {name}: {e}")

    async def _scan_loop(self) -> None:
        """Periodic network scan."""
        while self._running:
            try:
                await self._scan_network()
            except Exception as e:
                logger.error(f"Network scan error: {e}")
            await asyncio.sleep(self.scan_interval)

    async def _scan_network(self) -> None:
        """Scan local network for devices."""
        # Get local network range
        network = self._get_local_network()
        if not network:
            return

        # Quick port scan for common device ports
        common_ports = {
            22: (DeviceType.COMPUTER, ConnectionProtocol.SSH),
            23: (DeviceType.ROUTER, ConnectionProtocol.CUSTOM),
            80: (DeviceType.UNKNOWN, ConnectionProtocol.HTTP),
            443: (DeviceType.UNKNOWN, ConnectionProtocol.HTTPS),
            5555: (DeviceType.ANDROID, ConnectionProtocol.ADB),
            8080: (DeviceType.UNKNOWN, ConnectionProtocol.HTTP),
            8123: (DeviceType.HOME_ASSISTANT, ConnectionProtocol.HOME_ASSISTANT),
            8443: (DeviceType.CAMERA, ConnectionProtocol.HTTPS),
            9000: (DeviceType.SPEAKER, ConnectionProtocol.HTTP),  # Sonos
            9100: (DeviceType.CAMERA, ConnectionProtocol.ONVIF),
        }

        # Scan a subset of IPs (don't scan entire /24 every time)
        import random
        hosts = list(network.hosts())
        sample_size = min(20, len(hosts))
        sampled_hosts = random.sample(hosts, sample_size)

        for ip in sampled_hosts:
            ip_str = str(ip)
            for port, (device_type, protocol) in common_ports.items():
                if await self._check_port(ip_str, port, timeout=0.5):
                    # Try to get device name
                    name = await self._get_device_name(ip_str, port, protocol)
                    if not name:
                        name = f"{device_type.value}-{ip_str.replace('.', '-')[-6:]}"

                    device = DiscoveredDevice(
                        name=name,
                        device_type=device_type,
                        protocol=protocol,
                        address=ip_str,
                        port=port,
                        metadata={'discovered_by': 'port_scan'}
                    )
                    self._notify(device)
                    break  # Only report first open port per IP

    def _get_local_network(self) -> Optional[IPv4Network]:
        """Get local network CIDR."""
        if self.network_range:
            try:
                return IPv4Network(self.network_range, strict=False)
            except Exception:
                pass

        try:
            # Get default gateway interface IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Assume /24 network
            return IPv4Network(f"{local_ip}/24", strict=False)
        except Exception:
            return None

    async def _check_port(self, host: str, port: int, timeout: float = 1.0) -> bool:
        """Check if a TCP port is open."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _get_device_name(self, ip: str, port: int, protocol: ConnectionProtocol) -> Optional[str]:
        """Try to get device name via HTTP/UPnP."""
        try:
            if protocol in (ConnectionProtocol.HTTP, ConnectionProtocol.HTTPS):
                import aiohttp
                scheme = "https" if protocol == ConnectionProtocol.HTTPS else "http"
                url = f"{scheme}://{ip}:{port}/"
                timeout = aiohttp.ClientTimeout(total=2)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        # Try to get server header or title
                        server = resp.headers.get('Server', '')
                        if server:
                            return server.split('/')[0]
        except Exception:
            pass
        return None


class BluetoothScanner(BaseScanner):
    """
    Bluetooth LE scanner using bleak.
    Discovers: BLE sensors, actuators, beacons, phones, wearables.
    """

    def __init__(
        self,
        callback: Optional[Callable[[DiscoveredDevice], None]] = None,
        scan_interval: int = 30,
        continuous: bool = True
    ):
        super().__init__(callback)
        self.scan_interval = scan_interval
        self.continuous = continuous
        self._scanner = None
        self._known_devices: set[str] = set()

        # Known BLE service UUIDs to device type mapping
        self._service_mapping = {
            # Standard services
            "0000180d-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Heart Rate"),
            "0000180f-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Battery"),
            "0000181a-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Environmental"),
            "00001819-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Location"),
            # Common vendor services
            "0000fe95-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Xiaomi"),
            "0000fd3d-0000-1000-8000-00805f9b34fb": (DeviceType.SENSOR, "Qingping"),
            "0000181c-0000-1000-8000-00805f9b34fb": (DeviceType.ACTUATOR, "Generic"),
        }

    async def start(self) -> None:
        """Start Bluetooth LE scanning."""
        if self._running:
            return

        try:
            from bleak import BleakScanner

            self._running = True

            if self.continuous:
                self._scanner = BleakScanner()
                self._scanner.register_detection_callback(self._on_device_found)
                await self._scanner.start()
                logger.info("BluetoothScanner started (continuous)")
            else:
                # One-shot scan
                self._task = asyncio.create_task(self._scan_loop())

        except ImportError:
            logger.warning("bleak not available, Bluetooth discovery disabled")
        except Exception as e:
            logger.error(f"Failed to start Bluetooth scanner: {e}")

    async def stop(self) -> None:
        """Stop scanning."""
        self._running = False

        if self._scanner:
            try:
                await self._scanner.stop()
            except Exception:
                pass
            self._scanner = None

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("BluetoothScanner stopped")

    def _on_device_found(self, device, advertisement_data) -> None:
        """Callback for each discovered BLE device."""
        if not self._running:
            return

        try:
            address = device.address
            name = device.name or advertisement_data.local_name or f"BLE-{address.replace(':', '')[-6:]}"
            rssi = advertisement_data.rssi

            # Determine device type from service UUIDs
            device_type = DeviceType.SENSOR
            service_name = "Unknown"
            services = advertisement_data.service_uuids or []

            for uuid in services:
                uuid_lower = uuid.lower()
                if uuid_lower in self._service_mapping:
                    device_type, service_name = self._service_mapping[uuid_lower]
                    break

            # Check manufacturer data for known vendors
            manufacturer_data = advertisement_data.manufacturer_data or {}
            metadata = {'manufacturer_data': manufacturer_data}

            # Xiaomi (0x038F) / Qingping (0x045B) etc.
            for mfg_id, data in manufacturer_data.items():
                if mfg_id == 0x038F:
                    device_type = DeviceType.SENSOR
                    service_name = "Xiaomi"
                elif mfg_id == 0x045B:
                    device_type = DeviceType.SENSOR
                    service_name = "Qingping"

            # Create capabilities based on services
            capabilities = []
            for uuid in services:
                capabilities.append(DeviceCapability(
                    name=f"ble_service_{uuid.lower().replace('-', '_')}",
                    description=f"BLE Service: {uuid}",
                    parameters={"service_uuid": uuid}
                ))

            discovered = DiscoveredDevice(
                name=f"{name} ({service_name})",
                device_type=device_type,
                protocol=ConnectionProtocol.BLUETOOTH,
                address=address,
                metadata=metadata,
                capabilities=capabilities,
                rssi=rssi
            )

            # Avoid duplicate notifications
            key = f"{address}:{name}"
            if key not in self._known_devices:
                self._known_devices.add(key)
                self._notify(discovered)

        except Exception as e:
            logger.debug(f"Error processing BLE device: {e}")

    async def _scan_loop(self) -> None:
        """Periodic one-shot scans."""
        from bleak import BleakScanner

        while self._running:
            try:
                devices = await BleakScanner.discover(timeout=10.0)
                for device in devices:
                    # Create minimal advertisement data
                    class MockAdvData:
                        def __init__(self, d):
                            self.local_name = d.name
                            self.rssi = d.rssi
                            self.service_uuids = d.metadata.get('uuids', []) if d.metadata else []
                            self.manufacturer_data = d.metadata.get('manufacturer_data', {}) if d.metadata else {}

                    self._on_device_found(device, MockAdvData(device))

            except Exception as e:
                logger.error(f"Bluetooth scan error: {e}")

            await asyncio.sleep(self.scan_interval)


class DeviceDiscovery:
    """
    High-level device discovery coordinator.
    Manages network and Bluetooth scanners, registers devices with DeviceManager.
    """

    def __init__(self, device_manager=None):
        self.device_manager = device_manager or get_device_manager()
        self.network_scanner: Optional[NetworkScanner] = None
        self.bluetooth_scanner: Optional[BluetoothScanner] = None
        self._running = False

    async def start(
        self,
        enable_network: bool = True,
        enable_bluetooth: bool = True,
        network_interval: int = 60,
        bluetooth_interval: int = 30,
        network_range: Optional[str] = None
    ) -> None:
        """Start all discovery services."""
        if self._running:
            return

        self._running = True

        if enable_network:
            self.network_scanner = NetworkScanner(
                callback=self._on_device_discovered,
                scan_interval=network_interval,
                network_range=network_range
            )
            await self.network_scanner.start()

        if enable_bluetooth:
            self.bluetooth_scanner = BluetoothScanner(
                callback=self._on_device_discovered,
                scan_interval=bluetooth_interval,
                continuous=True
            )
            await self.bluetooth_scanner.start()

        logger.info("DeviceDiscovery started")

    async def stop(self) -> None:
        """Stop all discovery services."""
        self._running = False

        if self.network_scanner:
            await self.network_scanner.stop()
            self.network_scanner = None

        if self.bluetooth_scanner:
            await self.bluetooth_scanner.stop()
            self.bluetooth_scanner = None

        logger.info("DeviceDiscovery stopped")

    def _on_device_discovered(self, discovered: DiscoveredDevice) -> None:
        """Handle discovered device - register with DeviceManager."""
        try:
            # Check if already registered (by address)
            existing = None
            for device in self.device_manager.registry.list_all():
                if device.address == discovered.address and device.protocol == discovered.protocol:
                    existing = device
                    break

            if existing:
                # Update last seen
                self.device_manager.registry.update_last_seen(existing.id)
                return

            # Register new device
            device = self.device_manager.register_discovered_device(
                name=discovered.name,
                device_type=discovered.device_type,
                protocol=discovered.protocol,
                address=discovered.address,
                port=discovered.port,
                metadata=discovered.metadata,
                capabilities=discovered.capabilities
            )

            logger.info(f"Discovered new device: {device.name} ({device.type.value}) at {device.address}")

        except Exception as e:
            logger.error(f"Error registering discovered device: {e}")

    async def scan_once(self) -> list[DiscoveredDevice]:
        """Perform a one-time network scan and return results."""
        results = []

        def collect(device: DiscoveredDevice):
            results.append(device)

        # Network scan
        scanner = NetworkScanner(callback=collect, scan_interval=0)
        await scanner._scan_network()

        # Bluetooth scan
        bt_scanner = BluetoothScanner(callback=collect, scan_interval=0, continuous=False)
        from bleak import BleakScanner
        devices = await BleakScanner.discover(timeout=10.0)
        for device in devices:
            class MockAdvData:
                def __init__(self, d):
                    self.local_name = d.name
                    self.rssi = d.rssi
                    self.service_uuids = d.metadata.get('uuids', []) if d.metadata else []
                    self.manufacturer_data = d.metadata.get('manufacturer_data', {}) if d.metadata else {}
            bt_scanner._on_device_found(device, MockAdvData(device))

        return results


# Convenience function
async def discover_devices(
    enable_network: bool = True,
    enable_bluetooth: bool = True,
    timeout: int = 15
) -> list[DiscoveredDevice]:
    """Quick one-shot device discovery."""
    discovery = DeviceDiscovery()
    await discovery.start(enable_network, enable_bluetooth, network_interval=0, bluetooth_interval=0)
    await asyncio.sleep(timeout)
    await discovery.stop()
    return []