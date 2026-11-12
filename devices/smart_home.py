"""
Smart Home Manager - Home Assistant, Matter/Thread, and generic IoT integration.
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict, List, Callable

import aiohttp

from .manager import Device, DeviceType, ConnectionProtocol, DeviceCapability

logger = logging.getLogger(__name__)


class HAEntityDomain(Enum):
    """Home Assistant entity domains."""
    LIGHT = "light"
    SWITCH = "switch"
    CLIMATE = "climate"
    COVER = "cover"
    FAN = "fan"
    MEDIA_PLAYER = "media_player"
    CAMERA = "camera"
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    LOCK = "lock"
    ALARM_CONTROL_PANEL = "alarm_control_panel"
    VACUUM = "vacuum"
    WATER_HEATER = "water_heater"
    HUMIDIFIER = "humidifier"
    REMOTE = "remote"
    SCENE = "scene"
    SCRIPT = "script"
    AUTOMATION = "automation"
    INPUT_BOOLEAN = "input_boolean"
    INPUT_NUMBER = "input_number"
    INPUT_SELECT = "input_select"
    INPUT_TEXT = "input_text"
    DEVICE_TRACKER = "device_tracker"
    PERSON = "person"
    ZONE = "zone"


@dataclass
class HAEntity:
    """Home Assistant entity representation."""
    entity_id: str
    domain: str
    state: str
    attributes: Dict = field(default_factory=dict)
    last_updated: Optional[datetime] = None
    last_changed: Optional[datetime] = None
    context: Dict = field(default_factory=dict)

    @property
    def friendly_name(self) -> str:
        return self.attributes.get('friendly_name', self.entity_id)

    @property
    def device_class(self) -> Optional[str]:
        return self.attributes.get('device_class')

    @property
    def unit_of_measurement(self) -> Optional[str]:
        return self.attributes.get('unit_of_measurement')


@dataclass
class MatterDevice:
    """Matter/Thread device representation."""
    node_id: int
    fabric_id: int
    vendor_id: int
    product_id: int
    name: str
    endpoints: List[Dict] = field(default_factory=list)
    commissioning_data: Optional[str] = None


class SmartHomeManager:
    """
    Manages smart home integrations:
    - Home Assistant (REST API + WebSocket)
    - Matter/Thread (via python-matter-server or chip-tool)
    - Generic MQTT devices
    """

    def __init__(self):
        self._ha_sessions: Dict[str, aiohttp.ClientSession] = {}
        self._ha_ws: Dict[str, Any] = {}
        self._ha_configs: Dict[str, Dict] = {}
        self._matter_controller = None
        self._entity_cache: Dict[str, List[HAEntity]] = {}
        self._event_callbacks: List[Callable] = []

    # ===== Home Assistant =====

    def register_hass(self, device_id: str, url: str, token: str, verify_ssl: bool = True) -> None:
        """Register Home Assistant instance."""
        self._ha_configs[device_id] = {
            'url': url.rstrip('/'),
            'token': token,
            'verify_ssl': verify_ssl
        }

    async def _get_ha_session(self, device_id: str) -> Optional[aiohttp.ClientSession]:
        """Get or create HA session."""
        if device_id in self._ha_sessions:
            session = self._ha_sessions[device_id]
            if not session.closed:
                return session

        config = self._ha_configs.get(device_id)
        if not config:
            return None

        headers = {
            'Authorization': f'Bearer {config["token"]}',
            'Content-Type': 'application/json'
        }

        connector = aiohttp.TCPConnector(ssl=config['verify_ssl'])
        session = aiohttp.ClientSession(
            connector=connector,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self._ha_sessions[device_id] = session
        return session

    async def hass_get_states(self, device_id: str) -> List[HAEntity]:
        """Get all entity states."""
        session = await self._get_ha_session(device_id)
        if not session:
            return []

        config = self._ha_configs[device_id]
        try:
            async with session.get(f"{config['url']}/api/states") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    entities = []
                    for item in data:
                        entity = HAEntity(
                            entity_id=item['entity_id'],
                            domain=item['entity_id'].split('.')[0],
                            state=item['state'],
                            attributes=item.get('attributes', {}),
                            last_updated=item.get('last_updated'),
                            last_changed=item.get('last_changed'),
                            context=item.get('context', {})
                        )
                        entities.append(entity)

                    self._entity_cache[device_id] = entities
                    return entities
        except Exception as e:
            logger.error(f"HA get_states error: {e}")

        return []

    async def hass_get_state(self, device_id: str, entity_id: str) -> Optional[HAEntity]:
        """Get single entity state."""
        session = await self._get_ha_session(device_id)
        if not session:
            return None

        config = self._ha_configs[device_id]
        try:
            async with session.get(f"{config['url']}/api/states/{entity_id}") as resp:
                if resp.status == 200:
                    item = await resp.json()
                    return HAEntity(
                        entity_id=item['entity_id'],
                        domain=item['entity_id'].split('.')[0],
                        state=item['state'],
                        attributes=item.get('attributes', {}),
                        last_updated=item.get('last_updated'),
                        last_changed=item.get('last_changed'),
                        context=item.get('context', {})
                    )
        except Exception as e:
            logger.error(f"HA get_state error: {e}")

        return None

    async def hass_call_service(
        self,
        device_id: str,
        domain: str,
        service: str,
        service_data: Dict = None,
        target: Dict = None
    ) -> Dict:
        """Call Home Assistant service."""
        session = await self._get_ha_session(device_id)
        if not session:
            return {"success": False, "error": "Not connected"}

        config = self._ha_configs[device_id]
        data = service_data or {}
        if target:
            data['target'] = target

        try:
            async with session.post(
                f"{config['url']}/api/services/{domain}/{service}",
                json=data
            ) as resp:
                result = {"success": resp.status == 200, "status": resp.status}
                if resp.status == 200:
                    result['data'] = await resp.json()
                else:
                    result['error'] = await resp.text()
                return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def hass_fire_event(self, device_id: str, event_type: str, event_data: Dict = None) -> Dict:
        """Fire custom event."""
        session = await self._get_ha_session(device_id)
        if not session:
            return {"success": False, "error": "Not connected"}

        config = self._ha_configs[device_id]
        try:
            async with session.post(
                f"{config['url']}/api/events/{event_type}",
                json=event_data or {}
            ) as resp:
                return {"success": resp.status == 200, "status": resp.status}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Common service wrappers
    async def hass_turn_on(self, device_id: str, entity_id: str, **kwargs) -> Dict:
        domain = entity_id.split('.')[0]
        return await self.hass_call_service(device_id, domain, 'turn_on', {'entity_id': entity_id, **kwargs})

    async def hass_turn_off(self, device_id: str, entity_id: str) -> Dict:
        domain = entity_id.split('.')[0]
        return await self.hass_call_service(device_id, domain, 'turn_off', {'entity_id': entity_id})

    async def hass_toggle(self, device_id: str, entity_id: str) -> Dict:
        domain = entity_id.split('.')[0]
        return await self.hass_call_service(device_id, domain, 'toggle', {'entity_id': entity_id})

    async def hass_set_light(
        self,
        device_id: str,
        entity_id: str,
        brightness: int = None,
        color_temp: int = None,
        rgb_color: List[int] = None,
        hs_color: List[float] = None,
        xy_color: List[float] = None,
        transition: float = None,
        **kwargs
    ) -> Dict:
        """Set light state."""
        data = {'entity_id': entity_id}
        if brightness is not None:
            data['brightness'] = brightness
        if color_temp is not None:
            data['color_temp'] = color_temp
        if rgb_color is not None:
            data['rgb_color'] = rgb_color
        if hs_color is not None:
            data['hs_color'] = hs_color
        if xy_color is not None:
            data['xy_color'] = xy_color
        if transition is not None:
            data['transition'] = transition
        data.update(kwargs)
        return await self.hass_call_service(device_id, 'light', 'turn_on', data)

    async def hass_set_climate(
        self,
        device_id: str,
        entity_id: str,
        temperature: float = None,
        target_temp_low: float = None,
        target_temp_high: float = None,
        hvac_mode: str = None,
        preset_mode: str = None,
        fan_mode: str = None,
        **kwargs
    ) -> Dict:
        """Set climate entity."""
        data = {'entity_id': entity_id}
        if temperature is not None:
            data['temperature'] = temperature
        if target_temp_low is not None:
            data['target_temp_low'] = target_temp_low
        if target_temp_high is not None:
            data['target_temp_high'] = target_temp_high
        if hvac_mode is not None:
            data['hvac_mode'] = hvac_mode
        if preset_mode is not None:
            data['preset_mode'] = preset_mode
        if fan_mode is not None:
            data['fan_mode'] = fan_mode
        data.update(kwargs)
        return await self.hass_call_service(device_id, 'climate', 'set_temperature', data)

    async def hass_set_cover(
        self,
        device_id: str,
        entity_id: str,
        position: int = None,
        tilt_position: int = None,
        **kwargs
    ) -> Dict:
        """Set cover position."""
        data = {'entity_id': entity_id}
        if position is not None:
            data['position'] = position
        if tilt_position is not None:
            data['tilt_position'] = tilt_position
        data.update(kwargs)
        return await self.hass_call_service(device_id, 'cover', 'set_cover_position', data)

    async def hass_media_play(self, device_id: str, entity_id: str) -> Dict:
        return await self.hass_call_service(device_id, 'media_player', 'media_play', {'entity_id': entity_id})

    async def hass_media_pause(self, device_id: str, entity_id: str) -> Dict:
        return await self.hass_call_service(device_id, 'media_player', 'media_pause', {'entity_id': entity_id})

    async def hass_media_stop(self, device_id: str, entity_id: str) -> Dict:
        return await self.hass_call_service(device_id, 'media_player', 'media_stop', {'entity_id': entity_id})

    async def hass_media_volume(self, device_id: str, entity_id: str, level: float) -> Dict:
        return await self.hass_call_service(device_id, 'media_player', 'volume_set', {
            'entity_id': entity_id,
            'volume_level': level
        })

    async def hass_lock(self, device_id: str, entity_id: str) -> Dict:
        return await self.hass_call_service(device_id, 'lock', 'lock', {'entity_id': entity_id})

    async def hass_unlock(self, device_id: str, entity_id: str) -> Dict:
        return await self.hass_call_service(device_id, 'lock', 'unlock', {'entity_id': entity_id})

    # ===== WebSocket for real-time updates =====

    async def hass_ws_connect(self, device_id: str) -> bool:
        """Connect to HA WebSocket for real-time events."""
        config = self._ha_configs.get(device_id)
        if not config:
            return False

        try:
            session = await self._get_ha_session(device_id)
            ws = await session.ws_connect(f"{config['url'].replace('http', 'ws')}/api/websocket")

            # Authenticate
            await ws.send_json({"type": "auth", "access_token": config['token']})
            msg = await ws.receive()
            auth_resp = msg.json() if msg.type == aiohttp.WSMsgType.TEXT else None

            if not auth_resp or auth_resp.get('type') != 'auth_ok':
                logger.error(f"HA WS auth failed: {auth_resp}")
                await ws.close()
                return False

            # Subscribe to state changes
            await ws.send_json({
                "id": 1,
                "type": "subscribe_events",
                "event_type": "state_changed"
            })

            self._ha_ws[device_id] = ws

            # Start listener task
            asyncio.create_task(self._ha_ws_listener(device_id, ws))
            return True

        except Exception as e:
            logger.error(f"HA WS connect error: {e}")
            return False

    async def _ha_ws_listener(self, device_id: str, ws) -> None:
        """Listen for HA WebSocket events."""
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.json()
                    if data.get('type') == 'event' and data.get('event', {}).get('event_type') == 'state_changed':
                        event_data = data['event']['data']
                        entity_id = event_data.get('entity_id')
                        new_state = event_data.get('new_state')
                        if new_state:
                            entity = HAEntity(
                                entity_id=entity_id,
                                domain=entity_id.split('.')[0],
                                state=new_state['state'],
                                attributes=new_state.get('attributes', {}),
                                last_updated=new_state.get('last_updated'),
                                last_changed=new_state.get('last_changed'),
                                context=new_state.get('context', {})
                            )
                            # Update cache
                            if device_id in self._entity_cache:
                                for i, e in enumerate(self._entity_cache[device_id]):
                                    if e.entity_id == entity_id:
                                        self._entity_cache[device_id][i] = entity
                                        break

                            # Emit event
                            self._emit_event('entity_state_changed', device_id, entity)
        except Exception as e:
            logger.error(f"HA WS listener error: {e}")
        finally:
            self._ha_ws.pop(device_id, None)

    # ===== Matter/Thread =====

    async def matter_init(self, controller_path: str = "chip-tool") -> bool:
        """Initialize Matter controller."""
        self._matter_controller = controller_path
        # Verify chip-tool exists
        try:
            proc = await asyncio.create_subprocess_exec(
                controller_path, '--help',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    async def matter_commission(
        self,
        discriminator: int,
        setup_pin: int,
        node_id: int = None
    ) -> Dict:
        """Commission a Matter device."""
        if not self._matter_controller:
            return {"success": False, "error": "Matter controller not initialized"}

        args = [self._matter_controller, 'pairing', 'code', 'wifi']
        if node_id:
            args.append(str(node_id))
        args.extend([str(discriminator), str(setup_pin)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(),
                "stderr": stderr.decode()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def matter_commission_ble(
        self,
        discriminator: int,
        setup_pin: int,
        node_id: int = None
    ) -> Dict:
        """Commission Matter device over BLE."""
        if not self._matter_controller:
            return {"success": False, "error": "Matter controller not initialized"}

        args = [self._matter_controller, 'pairing', 'ble-wifi']
        if node_id:
            args.append(str(node_id))
        args.extend([str(discriminator), str(setup_pin)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(),
                "stderr": stderr.decode()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def matter_on_off(self, node_id: int, endpoint: int, on: bool) -> Dict:
        """Control Matter On/Off cluster."""
        if not self._matter_controller:
            return {"success": False, "error": "Matter controller not initialized"}

        cmd = 'on' if on else 'off'
        args = [self._matter_controller, 'onoff', cmd, str(node_id), str(endpoint)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {"success": proc.returncode == 0, "stdout": stdout.decode()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def matter_level_control(self, node_id: int, endpoint: int, level: int) -> Dict:
        """Control Matter Level cluster (0-254)."""
        if not self._matter_controller:
            return {"success": False, "error": "Matter controller not initialized"}

        args = [self._matter_controller, 'levelcontrol', 'movetolevel', str(node_id), str(endpoint), str(level), '0', '0', '0']

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {"success": proc.returncode == 0, "stdout": stdout.decode()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def matter_color_control(self, node_id: int, endpoint: int, hue: int, saturation: int) -> Dict:
        """Control Matter Color Control cluster."""
        if not self._matter_controller:
            return {"success": False, "error": "Matter controller not initialized"}

        args = [self._matter_controller, 'colorcontrol', 'movetohue', str(node_id), str(endpoint), str(hue), '0', '0', '0']

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            return {"success": proc.returncode == 0, "stdout": stdout.decode()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ===== Generic device control =====

    def on_event(self, callback: Callable) -> None:
        """Register event callback."""
        self._event_callbacks.append(callback)

    def _emit_event(self, event_type: str, device_id: str, data: Any) -> None:
        for callback in self._event_callbacks:
            try:
                callback({
                    'type': event_type,
                    'device_id': device_id,
                    'data': data,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    async def execute_command(self, device: Device, command: str, parameters: Dict = None) -> Dict:
        """Execute smart home command."""
        params = parameters or {}

        if device.protocol == ConnectionProtocol.HOME_ASSISTANT:
            if command == 'get_states':
                entities = await self.hass_get_states(device.id)
                return {"success": True, "entities": [e.__dict__ for e in entities]}

            elif command == 'get_state':
                entity = await self.hass_get_state(device.id, params.get('entity_id'))
                return {"success": True, "entity": entity.__dict__ if entity else None}

            elif command == 'call_service':
                return await self.hass_call_service(
                    device.id,
                    params.get('domain'),
                    params.get('service'),
                    params.get('service_data'),
                    params.get('target')
                )

            elif command == 'turn_on':
                return await self.hass_turn_on(device.id, params.get('entity_id'), **params.get('kwargs', {}))

            elif command == 'turn_off':
                return await self.hass_turn_off(device.id, params.get('entity_id'))

            elif command == 'toggle':
                return await self.hass_toggle(device.id, params.get('entity_id'))

            elif command == 'set_light':
                return await self.hass_set_light(device.id, params.get('entity_id'), **params)

            elif command == 'set_climate':
                return await self.hass_set_climate(device.id, params.get('entity_id'), **params)

            elif command == 'set_cover':
                return await self.hass_set_cover(device.id, params.get('entity_id'), **params)

            elif command == 'media_play':
                return await self.hass_media_play(device.id, params.get('entity_id'))

            elif command == 'media_pause':
                return await self.hass_media_pause(device.id, params.get('entity_id'))

            elif command == 'media_volume':
                return await self.hass_media_volume(device.id, params.get('entity_id'), params.get('level'))

            elif command == 'lock':
                return await self.hass_lock(device.id, params.get('entity_id'))

            elif command == 'unlock':
                return await self.hass_unlock(device.id, params.get('entity_id'))

        elif device.protocol == ConnectionProtocol.MATTER:
            if command == 'on_off':
                return await self.matter_on_off(params.get('node_id'), params.get('endpoint'), params.get('on'))
            elif command == 'level':
                return await self.matter_level_control(params.get('node_id'), params.get('endpoint'), params.get('level'))
            elif command == 'color':
                return await self.matter_color_control(params.get('node_id'), params.get('endpoint'),
                                                       params.get('hue'), params.get('saturation'))

        return {"success": False, "error": f"Unsupported command: {command}"}

    async def close_all(self) -> None:
        """Close all connections."""
        for device_id, session in self._ha_sessions.items():
            if not session.closed:
                await session.close()

        for device_id, ws in self._ha_ws.items():
            if not ws.closed:
                await ws.close()


# Global instance
_smart_home_manager: Optional[SmartHomeManager] = None


def get_smart_home_manager() -> SmartHomeManager:
    """Get or create global SmartHomeManager instance."""
    global _smart_home_manager
    if _smart_home_manager is None:
        _smart_home_manager = SmartHomeManager()
    return _smart_home_manager