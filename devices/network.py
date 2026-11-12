"""
Network Manager - HTTP/REST API, SSH, MQTT, WebSocket device control.
Handles communication with network-connected devices.
"""
from __future__ import annotations
import asyncio
import json
import logging
import ssl
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Dict, List
from pathlib import Path

import aiohttp
import asyncssh

from .manager import Device, DeviceType, ConnectionProtocol, DeviceStatus

logger = logging.getLogger(__name__)


@dataclass
class NetworkDeviceConfig:
    """Configuration for a network device connection."""
    host: str
    port: int
    protocol: ConnectionProtocol
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    token: Optional[str] = None
    verify_ssl: bool = True
    timeout: float = 10.0
    extra: dict = field(default_factory=dict)


class NetworkManager:
    """
    Manages network connections to devices.
    Supports HTTP/REST, SSH, MQTT, WebSocket protocols.
    """

    def __init__(self):
        self._sessions: Dict[str, aiohttp.ClientSession] = {}
        self._ssh_clients: Dict[str, asyncssh.SSHClientConnection] = {}
        self._mqtt_clients: Dict[str, Any] = {}
        self._ws_connections: Dict[str, Any] = {}
        self._configs: Dict[str, NetworkDeviceConfig] = {}

    def register_device(self, device: Device, config: NetworkDeviceConfig) -> None:
        """Register device connection config."""
        self._configs[device.id] = config

    def get_config(self, device_id: str) -> Optional[NetworkDeviceConfig]:
        """Get device config."""
        return self._configs.get(device_id)

    # ===== HTTP/REST API =====

    async def _get_session(self, device_id: str) -> Optional[aiohttp.ClientSession]:
        """Get or create HTTP session for device."""
        if device_id in self._sessions:
            session = self._sessions[device_id]
            if not session.closed:
                return session

        config = self._configs.get(device_id)
        if not config:
            return None

        connector = aiohttp.TCPConnector(ssl=config.verify_ssl)
        timeout = aiohttp.ClientTimeout(total=config.timeout)

        headers = {}
        if config.api_key:
            headers['Authorization'] = f'Bearer {config.api_key}'
        elif config.token:
            headers['Authorization'] = f'Bearer {config.token}'

        session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        )
        self._sessions[device_id] = session
        return session

    async def http_request(
        self,
        device_id: str,
        method: str,
        path: str,
        data: Any = None,
        params: Dict = None,
        headers: Dict = None
    ) -> Dict:
        """Make HTTP request to device."""
        config = self._configs.get(device_id)
        if not config:
            return {"success": False, "error": "Device not configured"}

        session = await self._get_session(device_id)
        if not session:
            return {"success": False, "error": "Failed to create session"}

        url = f"{'https' if config.protocol == ConnectionProtocol.HTTPS else 'http'}://{config.host}:{config.port}{path}"

        try:
            async with session.request(
                method=method.upper(),
                url=url,
                json=data,
                params=params,
                headers=headers
            ) as resp:
                result = {
                    "success": True,
                    "status": resp.status,
                    "headers": dict(resp.headers)
                }

                content_type = resp.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    result['data'] = await resp.json()
                else:
                    result['data'] = await resp.text()

                if resp.status >= 400:
                    result['success'] = False
                    result['error'] = f"HTTP {resp.status}: {result['data']}"

                return result

        except asyncio.TimeoutError:
            return {"success": False, "error": "Request timeout"}
        except aiohttp.ClientError as e:
            return {"success": False, "error": f"HTTP error: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Request failed: {e}"}

    async def http_get(self, device_id: str, path: str, params: Dict = None) -> Dict:
        return await self.http_request(device_id, 'GET', path, params=params)

    async def http_post(self, device_id: str, path: str, data: Any = None) -> Dict:
        return await self.http_request(device_id, 'POST', path, data=data)

    async def http_put(self, device_id: str, path: str, data: Any = None) -> Dict:
        return await self.http_request(device_id, 'PUT', path, data=data)

    async def http_delete(self, device_id: str, path: str) -> Dict:
        return await self.http_request(device_id, 'DELETE', path)

    async def http_patch(self, device_id: str, path: str, data: Any = None) -> Dict:
        return await self.http_request(device_id, 'PATCH', path, data=data)

    # ===== SSH =====

    async def ssh_connect(self, device_id: str) -> bool:
        """Establish SSH connection."""
        if device_id in self._ssh_clients:
            client = self._ssh_clients[device_id]
            if not client.is_closed():
                return True

        config = self._configs.get(device_id)
        if not config or config.protocol != ConnectionProtocol.SSH:
            logger.error(f"Device {device_id} not configured for SSH")
            return False

        try:
            client = await asyncssh.connect(
                config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                known_hosts=None,  # Auto-accept for now
                client_keys=config.extra.get('client_keys'),
                connect_timeout=config.timeout
            )
            self._ssh_clients[device_id] = client
            logger.info(f"SSH connected to {config.host}")
            return True

        except Exception as e:
            logger.error(f"SSH connection error: {e}")
            return False

    async def ssh_exec(self, device_id: str, command: str) -> Dict:
        """Execute command via SSH."""
        if device_id not in self._ssh_clients:
            if not await self.ssh_connect(device_id):
                return {"success": False, "error": "SSH connection failed"}

        client = self._ssh_clients[device_id]
        try:
            result = await client.run(command, check=False)
            return {
                "success": result.exit_status == 0,
                "exit_code": result.exit_status,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except Exception as e:
            return {"success": False, "error": f"SSH exec error: {e}"}

    async def ssh_close(self, device_id: str) -> None:
        """Close SSH connection."""
        client = self._ssh_clients.pop(device_id, None)
        if client:
            client.close()
            await client.wait_closed()

    # ===== MQTT =====

    async def mqtt_connect(self, device_id: str) -> bool:
        """Connect to MQTT broker."""
        try:
            import paho.mqtt.client as mqtt
            from paho.mqtt.enums import CallbackAPIVersion

            config = self._configs.get(device_id)
            if not config or config.protocol != ConnectionProtocol.MQTT:
                return False

            client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=f"jarvis-{device_id}"
            )

            if config.username and config.password:
                client.username_pw_set(config.username, config.password)

            if config.extra.get('tls'):
                client.tls_set(
                    ca_certs=config.extra.get('ca_cert'),
                    certfile=config.extra.get('client_cert'),
                    keyfile=config.extra.get('client_key')
                )

            # Run in executor since paho is blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, client.connect, config.host, config.port, 60)
            client.loop_start()

            self._mqtt_clients[device_id] = client
            logger.info(f"MQTT connected to {config.host}")
            return True

        except Exception as e:
            logger.error(f"MQTT connection error: {e}")
            return False

    async def mqtt_publish(self, device_id: str, topic: str, payload: Any, qos: int = 0) -> Dict:
        """Publish MQTT message."""
        client = self._mqtt_clients.get(device_id)
        if not client:
            if not await self.mqtt_connect(device_id):
                return {"success": False, "error": "MQTT not connected"}

        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)

            # Run in executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, client.publish, topic, payload, qos
            )

            # Wait for publish confirmation
            if qos > 0:
                result.wait_for_publish(timeout=5)

            return {"success": True, "topic": topic}

        except Exception as e:
            return {"success": False, "error": f"MQTT publish error: {e}"}

    async def mqtt_subscribe(self, device_id: str, topic: str, callback: Callable, qos: int = 0) -> bool:
        """Subscribe to MQTT topic."""
        client = self._mqtt_clients.get(device_id)
        if not client:
            if not await self.mqtt_connect(device_id):
                return False

        def on_message(client, userdata, msg):
            try:
                payload = msg.payload.decode()
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    pass
                callback(msg.topic, payload)
            except Exception as e:
                logger.error(f"MQTT callback error: {e}")

        client.on_message = on_message
        client.subscribe(topic, qos)
        return True

    async def mqtt_close(self, device_id: str) -> None:
        """Close MQTT connection."""
        client = self._mqtt_clients.pop(device_id, None)
        if client:
            client.loop_stop()
            client.disconnect()

    # ===== WebSocket =====

    async def ws_connect(self, device_id: str) -> bool:
        """Connect to WebSocket."""
        config = self._configs.get(device_id)
        if not config or config.protocol != ConnectionProtocol.WEBSOCKET:
            return False

        try:
            session = await self._get_session(device_id)
            if not session:
                return False

            url = f"{'wss' if config.protocol == ConnectionProtocol.HTTPS else 'ws'}://{config.host}:{config.port}"
            ws = await session.ws_connect(url)
            self._ws_connections[device_id] = ws
            logger.info(f"WebSocket connected to {url}")
            return True

        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            return False

    async def ws_send(self, device_id: str, message: Any) -> Dict:
        """Send WebSocket message."""
        ws = self._ws_connections.get(device_id)
        if not ws or ws.closed:
            if not await self.ws_connect(device_id):
                return {"success": False, "error": "WebSocket not connected"}

        try:
            if isinstance(message, (dict, list)):
                await ws.send_json(message)
            else:
                await ws.send_str(str(message))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"WS send error: {e}"}

    async def ws_receive(self, device_id: str, timeout: float = 5.0) -> Optional[Any]:
        """Receive WebSocket message."""
        ws = self._ws_connections.get(device_id)
        if not ws or ws.closed:
            return None

        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    return json.loads(msg.data)
                except json.JSONDecodeError:
                    return msg.data
            elif msg.type == aiohttp.WSMsgType.BINARY:
                return msg.data
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"WS receive error: {e}")
            return None

    async def ws_close(self, device_id: str) -> None:
        """Close WebSocket connection."""
        ws = self._ws_connections.pop(device_id, None)
        if ws and not ws.closed:
            await ws.close()

    # ===== Home Assistant =====

    async def hass_call_service(
        self,
        device_id: str,
        domain: str,
        service: str,
        service_data: Dict = None
    ) -> Dict:
        """Call Home Assistant service."""
        return await self.http_post(
            device_id,
            f"/api/services/{domain}/{service}",
            data=service_data or {}
        )

    async def hass_get_state(self, device_id: str, entity_id: str) -> Dict:
        """Get Home Assistant entity state."""
        return await self.http_get(device_id, f"/api/states/{entity_id}")

    async def hass_get_states(self, device_id: str) -> Dict:
        """Get all Home Assistant states."""
        return await self.http_get(device_id, "/api/states")

    # ===== Generic device control =====

    async def execute_command(self, device: Device, command: str, parameters: Dict = None) -> Dict:
        """Execute command based on device protocol."""
        config = self._configs.get(device.id)
        if not config:
            return {"success": False, "error": "Device not configured"}

        params = parameters or {}

        if config.protocol in (ConnectionProtocol.HTTP, ConnectionProtocol.HTTPS):
            # Generic REST command
            path = params.get('path', f"/api/{command}")
            method = params.get('method', 'POST').upper()
            data = params.get('data')

            if method == 'GET':
                return await self.http_get(device.id, path, params=data)
            elif method == 'POST':
                return await self.http_post(device.id, path, data=data)
            elif method == 'PUT':
                return await self.http_put(device.id, path, data=data)
            elif method == 'DELETE':
                return await self.http_delete(device.id, path)
            elif method == 'PATCH':
                return await self.http_patch(device.id, path, data=data)
            else:
                return await self.http_request(device.id, method, path, data=data)

        elif config.protocol == ConnectionProtocol.SSH:
            return await self.ssh_exec(device.id, params.get('command', command))

        elif config.protocol == ConnectionProtocol.MQTT:
            topic = params.get('topic', f"jarvis/{device.id}/{command}")
            payload = params.get('payload', {})
            return await self.mqtt_publish(device.id, topic, payload, params.get('qos', 0))

        elif config.protocol == ConnectionProtocol.WEBSOCKET:
            return await self.ws_send(device.id, params.get('message', {"command": command, **params}))

        elif config.protocol == ConnectionProtocol.HOME_ASSISTANT:
            if command == 'call_service':
                return await self.hass_call_service(
                    device.id,
                    params.get('domain'),
                    params.get('service'),
                    params.get('service_data')
                )
            elif command == 'get_state':
                return await self.hass_get_state(device.id, params.get('entity_id'))
            elif command == 'get_states':
                return await self.hass_get_states(device.id)

        return {"success": False, "error": f"Unsupported protocol: {config.protocol}"}

    async def close_all(self) -> None:
        """Close all connections."""
        for device_id in list(self._sessions.keys()):
            session = self._sessions.pop(device_id)
            if not session.closed:
                await session.close()

        for device_id in list(self._ssh_clients.keys()):
            await self.ssh_close(device_id)

        for device_id in list(self._mqtt_clients.keys()):
            await self.mqtt_close(device_id)

        for device_id in list(self._ws_connections.keys()):
            await self.ws_close(device_id)


# Global instance
_network_manager: Optional[NetworkManager] = None


def get_network_manager() -> NetworkManager:
    """Get or create global NetworkManager instance."""
    global _network_manager
    if _network_manager is None:
        _network_manager = NetworkManager()
    return _network_manager