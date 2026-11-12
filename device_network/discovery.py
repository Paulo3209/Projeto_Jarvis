"""
Network Discovery - mDNS/zeroconf and network scanning for device discovery.
"""
from __future__ import annotations
import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener, ServiceInfo
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryConfig:
    """Discovery configuration."""
    service_type: str = "_jarvis._tcp.local."
    scan_interval: int = 30
    timeout: int = 5
    ports: List[int] = field(default_factory=lambda: [8765, 8766, 8767])
    network_range: str = "192.168.1.0/24"
    enable_mdns: bool = True
    enable_port_scan: bool = True


@dataclass
class DiscoveredDevice:
    """Discovered device information."""
    name: str
    address: str
    port: int
    service_type: str
    properties: Dict[str, str] = field(default_factory=dict)
    discovered_at: datetime = field(default_factory=datetime.now)
    device_id: str = ""
    role: str = ""
    device_type: str = ""
    platform: str = ""


class NetworkDiscovery:
    """
    Discovers JARVIS devices on the network using mDNS and port scanning.
    """

    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DiscoveryConfig()
        self._zeroconf: Optional[Zeroconf] = None
        self._browser: Optional[ServiceBrowser] = None
        self._discovered: Dict[str, DiscoveredDevice] = {}
        self._callbacks: List[Callable[[DiscoveredDevice], None]] = []
        self._running = False

    def add_callback(self, callback: Callable[[DiscoveredDevice], None]) -> None:
        """Add callback for new device discovery."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[DiscoveredDevice], None]) -> None:
        """Remove callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def start(self) -> None:
        """Start discovery."""
        self._running = True

        if self.config.enable_mdns and ZEROCONF_AVAILABLE:
            await self._start_mdns()

        if self.config.enable_port_scan:
            asyncio.create_task(self._port_scan_loop())

        logger.info("Network discovery started")

    async def _start_mdns(self) -> None:
        """Start mDNS discovery."""
        self._zeroconf = Zeroconf()

        class JarvisListener(ServiceListener):
            def __init__(self, discovery):
                self.discovery = discovery

            def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info:
                    self.discovery._on_service_discovered(info)

            def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                # Device gone
                pass

            def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info:
                    self.discovery._on_service_discovered(info)

        listener = JarvisListener(self)
        self._browser = ServiceBrowser(self._zeroconf, self.config.service_type, listener)

    def _on_service_discovered(self, info: ServiceInfo) -> None:
        """Handle discovered service."""
        addresses = info.parsed_addresses()
        if not addresses:
            return

        address = addresses[0]
        port = info.port

        # Parse properties
        properties = {}
        if info.properties:
            for k, v in info.properties.items():
                try:
                    properties[k.decode()] = v.decode() if isinstance(v, bytes) else str(v)
                except Exception:
                    pass

        device = DiscoveredDevice(
            name=info.name,
            address=address,
            port=port,
            service_type=info.type,
            properties=properties,
            device_id=properties.get("device_id", ""),
            role=properties.get("role", ""),
            device_type=properties.get("device_type", ""),
            platform=properties.get("platform", ""),
        )

        key = f"{address}:{port}"
        if key not in self._discovered:
            logger.info(f"Discovered device via mDNS: {device.name} at {address}:{port}")
            for callback in self._callbacks:
                try:
                    callback(device)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        self._discovered[key] = device

    async def _port_scan_loop(self) -> None:
        """Periodic port scanning."""
        while self._running:
            try:
                await self._scan_network()
            except Exception as e:
                logger.error(f"Port scan error: {e}")

            await asyncio.sleep(self.config.scan_interval)

    async def _scan_network(self) -> None:
        """Scan network for JARVIS ports."""
        import ipaddress

        network = ipaddress.ip_network(self.config.network_range, strict=False)
        hosts = [str(ip) for ip in network.hosts()]

        # Limit concurrent scans
        semaphore = asyncio.Semaphore(50)

        async def scan_host(host: str):
            async with semaphore:
                for port in self.config.ports:
                    if await self._check_port(host, port):
                        await self._probe_device(host, port)

        tasks = [scan_host(host) for host in hosts]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_port(self, host: str, port: int) -> bool:
        """Check if port is open."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.config.timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _probe_device(self, host: str, port: int) -> None:
        """Probe device for JARVIS info."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.config.timeout
            )

            # Send probe message
            probe = {"type": "probe", "timestamp": time.time()}
            writer.write(json.dumps(probe).encode())
            await writer.drain()

            # Read response
            data = await asyncio.wait_for(reader.read(8192), timeout=2)
            writer.close()
            await writer.wait_closed()

            if data:
                try:
                    response = json.loads(data.decode())
                    if response.get("type") == "probe_response":
                        device = DiscoveredDevice(
                            name=response.get("name", f"jarvis-{host}"),
                            address=host,
                            port=port,
                            service_type="port_scan",
                            properties=response.get("properties", {}),
                            device_id=response.get("device_id", ""),
                            role=response.get("role", ""),
                            device_type=response.get("device_type", ""),
                            platform=response.get("platform", ""),
                        )
                        key = f"{host}:{port}"
                        if key not in self._discovered:
                            logger.info(f"Discovered device via port scan: {device.name} at {host}:{port}")
                            for callback in self._callbacks:
                                try:
                                    callback(device)
                                except Exception as e:
                                    logger.error(f"Callback error: {e}")
                        self._discovered[key] = device
                except Exception:
                    pass

        except Exception:
            pass

    def get_discovered(self) -> List[DiscoveredDevice]:
        """Get all discovered devices."""
        return list(self._discovered.values())

    def get_device(self, address: str, port: int) -> Optional[DiscoveredDevice]:
        """Get specific device."""
        return self._discovered.get(f"{address}:{port}")

    async def stop(self) -> None:
        """Stop discovery."""
        self._running = False

        if self._browser:
            self._browser.cancel()

        if self._zeroconf:
            self._zeroconf.close()

        logger.info("Network discovery stopped")


# For JSON handling
import json