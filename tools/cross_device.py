"""
Comunicação Cross-Device - MQTT/WebSocket para sincronizar JARVIS entre PC e Celular.
Arquitetura: Broker MQTT central (pode ser local ou cloud) + clientes em cada dispositivo.
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from core.plugin_system import tool, ToolCategory


# ==================== TIPOS ====================

class DeviceType(Enum):
    DESKTOP = "desktop"
    ANDROID = "android"
    IOS = "ios"
    SERVER = "server"


class MessageType(Enum):
    COMMAND = "command"
    RESPONSE = "response"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    SYNC = "sync"
    FILE_TRANSFER = "file_transfer"


@dataclass
class Device:
    id: str
    name: str
    type: DeviceType
    ip: str = ""
    port: int = 0
    capabilities: List[str] = field(default_factory=list)
    last_seen: str = ""
    status: str = "offline"  # online, offline, busy
    metadata: Dict = field(default_factory=dict)


@dataclass
class CrossDeviceMessage:
    id: str
    type: MessageType
    source_device: str
    target_device: str  # "" = broadcast
    payload: Dict
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: str = ""


# ==================== GERENCIADOR DE DISPOSITIVOS ====================

class DeviceRegistry:
    """Registro central de dispositivos conectados."""

    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self._local_device_id: Optional[str] = None

    def register_local(self, device_id: str, name: str, type: DeviceType, capabilities: List[str] = None):
        """Registra este dispositivo."""
        self._local_device_id = device_id
        self.devices[device_id] = Device(
            id=device_id,
            name=name,
            type=type,
            capabilities=capabilities or [],
            last_seen=datetime.now().isoformat(),
            status="online"
        )

    def update_device(self, device: Device):
        """Atualiza info de dispositivo (recebido via heartbeat)."""
        device.last_seen = datetime.now().isoformat()
        device.status = "online"
        self.devices[device.id] = device

    def get_device(self, device_id: str) -> Optional[Device]:
        return self.devices.get(device_id)

    def get_online_devices(self, device_type: DeviceType = None) -> List[Device]:
        now = datetime.now()
        online = []
        for d in self.devices.values():
            # Considera offline se sem heartbeat por 60s
            last = datetime.fromisoformat(d.last_seen) if d.last_seen else now
            if (now - last).total_seconds() < 60:
                if device_type is None or d.type == device_type:
                    online.append(d)
        return online

    def get_local_device(self) -> Optional[Device]:
        if self._local_device_id:
            return self.devices.get(self._local_device_id)
        return None


# Instância global
_device_registry = DeviceRegistry()


def get_device_registry() -> DeviceRegistry:
    return _device_registry


# ==================== MQTT CLIENT ====================

class MQTTBridge:
    """Bridge MQTT para comunicação cross-device."""

    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883,
                 username: str = "", password: str = "", topic_prefix: str = "jarvis"):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.topic_prefix = topic_prefix
        self.client = None
        self.connected = False
        self._message_handlers: Dict[str, Callable] = {}
        self._response_futures: Dict[str, asyncio.Future] = {}

    async def connect(self, device_id: str, device_name: str, device_type: DeviceType,
                      capabilities: List[str] = None) -> bool:
        """Conecta ao broker MQTT."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("[MQTTBridge] paho-mqtt não instalado. pip install paho-mqtt")
            return False

        self.client = mqtt.Client(client_id=device_id, protocol=mqtt.MQTTv5)
        if self.username:
            self.client.username_pw_set(self.username, self.password)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # Last Will Testament
        will_msg = json.dumps({
            "type": "event",
            "event": "device_offline",
            "device_id": device_id
        })
        self.client.will_set(f"{self.topic_prefix}/events", will_msg, qos=1, retain=False)

        try:
            self.client.connect_async(self.broker_host, self.broker_port, 60)
            self.client.loop_start()

            # Aguarda conexão
            for _ in range(50):
                if self.connected:
                    break
                await asyncio.sleep(0.1)

            if self.connected:
                # Registra dispositivo
                _device_registry.register_local(device_id, device_name, device_type, capabilities)
                await self._announce_online()
                return True
        except Exception as e:
            print(f"[MQTTBridge] Erro ao conectar: {e}")

        return False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            print(f"[MQTTBridge] Conectado ao broker {self.broker_host}")
            # Subscreve tópicos
            client.subscribe(f"{self.topic_prefix}/commands/+", qos=1)  # Comandos para este device
            client.subscribe(f"{self.topic_prefix}/broadcast", qos=1)   # Broadcast
            client.subscribe(f"{self.topic_prefix}/events", qos=1)      # Eventos
            client.subscribe(f"{self.topic_prefix}/sync", qos=1)        # Sync
            # Anuncia presença
            self._publish_event("device_online", {"device_id": client._client_id.decode()})
        else:
            print(f"[MQTTBridge] Falha na conexão: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic

            if topic.startswith(f"{self.topic_prefix}/commands/"):
                self._handle_command(payload)
            elif topic == f"{self.topic_prefix}/broadcast":
                self._handle_broadcast(payload)
            elif topic == f"{self.topic_prefix}/events":
                self._handle_event(payload)
            elif topic == f"{self.topic_prefix}/sync":
                self._handle_sync(payload)
        except Exception as e:
            print(f"[MQTTBridge] Erro processando mensagem: {e}")

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.connected = False
        print(f"[MQTTBridge] Desconectado: {rc}")

    def _handle_command(self, payload: dict):
        """Processa comando recebido."""
        msg = CrossDeviceMessage(**payload)
        # Resposta será enviada pelo handler registrado
        handler = self._message_handlers.get("command")
        if handler:
            asyncio.create_task(handler(msg))

    def _handle_broadcast(self, payload: dict):
        msg = CrossDeviceMessage(**payload)
        handler = self._message_handlers.get("broadcast")
        if handler:
            asyncio.create_task(handler(msg))

    def _handle_event(self, payload: dict):
        """Processa eventos (heartbeat, device online/offline)."""
        event_type = payload.get("event")
        if event_type == "heartbeat":
            device_data = payload.get("device")
            if device_data:
                device = Device(**device_data)
                _device_registry.update_device(device)
        elif event_type in ["device_online", "device_offline"]:
            device_id = payload.get("device_id")
            if device_id and device_id in _device_registry.devices:
                _device_registry.devices[device_id].status = "online" if event_type == "device_online" else "offline"

    def _handle_sync(self, payload: dict):
        msg = CrossDeviceMessage(**payload)
        handler = self._message_handlers.get("sync")
        if handler:
            asyncio.create_task(handler(msg))

    def on_message(self, msg_type: str, handler: Callable):
        """Registra handler para tipo de mensagem."""
        self._message_handlers[msg_type] = handler

    async def send_command(self, target_device: str, command: str, args: dict = None,
                          correlation_id: str = None) -> Optional[dict]:
        """Envia comando para dispositivo específico e aguarda resposta."""
        if not self.connected:
            return {"success": False, "error": "Não conectado ao broker"}

        corr_id = correlation_id or str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._response_futures[corr_id] = future

        msg = CrossDeviceMessage(
            id=str(uuid.uuid4()),
            type=MessageType.COMMAND,
            source_device=_device_registry.get_local_device().id if _device_registry.get_local_device() else "unknown",
            target_device=target_device,
            payload={"command": command, "args": args or {}},
            correlation_id=corr_id
        )

        self._publish(f"{self.topic_prefix}/commands/{target_device}", msg)

        try:
            response = await asyncio.wait_for(future, timeout=30)
            return response
        except asyncio.TimeoutError:
            return {"success": False, "error": "Timeout aguardando resposta"}
        finally:
            self._response_futures.pop(corr_id, None)

    async def broadcast(self, command: str, args: dict = None, target_type: DeviceType = None) -> dict:
        """Envia comando broadcast para todos ou tipo específico."""
        if not self.connected:
            return {"success": False, "error": "Não conectado"}

        msg = CrossDeviceMessage(
            id=str(uuid.uuid4()),
            type=MessageType.COMMAND,
            source_device=_device_registry.get_local_device().id if _device_registry.get_local_device() else "unknown",
            target_device="broadcast",
            payload={"command": command, "args": args or {}, "target_type": target_type.value if target_type else None}
        )

        self._publish(f"{self.topic_prefix}/broadcast", msg)
        return {"success": True, "message": "Broadcast enviado"}

    async def sync_state(self, key: str, value: Any, target_device: str = "") -> dict:
        """Sincroniza estado (chave-valor) entre dispositivos."""
        msg = CrossDeviceMessage(
            id=str(uuid.uuid4()),
            type=MessageType.SYNC,
            source_device=_device_registry.get_local_device().id if _device_registry.get_local_device() else "unknown",
            target_device=target_device,
            payload={"key": key, "value": value, "action": "set"}
        )

        self._publish(f"{self.topic_prefix}/sync", msg)
        return {"success": True}

    def _publish(self, topic: str, msg: CrossDeviceMessage):
        if self.client and self.connected:
            self.client.publish(topic, json.dumps(msg.__dict__), qos=1)

    def _publish_event(self, event: str, data: dict):
        payload = {
            "type": "event",
            "event": event,
            "device_id": _device_registry.get_local_device().id if _device_registry.get_local_device() else "unknown",
            "timestamp": datetime.now().isoformat(),
            **data
        }
        if self.client and self.connected:
            self.client.publish(f"{self.topic_prefix}/events", json.dumps(payload), qos=1)

    async def _announce_online(self):
        """Anuncia que este dispositivo está online."""
        local = _device_registry.get_local_device()
        if local:
            self._publish_event("device_online", {
                "device": {
                    "id": local.id,
                    "name": local.name,
                    "type": local.type.value,
                    "capabilities": local.capabilities,
                    "status": "online"
                }
            })

    async def send_heartbeat(self):
        """Envia heartbeat periódico."""
        local = _device_registry.get_local_device()
        if local and self.connected:
            self._publish_event("heartbeat", {"device": local.__dict__})

    def disconnect(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False


# Instância global
_mqtt_bridge: Optional[MQTTBridge] = None


def get_mqtt_bridge() -> MQTTBridge:
    global _mqtt_bridge
    if _mqtt_bridge is None:
        _mqtt_bridge = MQTTBridge()
    return _mqtt_bridge


# ==================== FERRAMENTAS PARA O BRAIN ====================

@tool(description="Configura e conecta ao broker MQTT para comunicação cross-device.", category=ToolCategory.SYSTEM)
def cross_device_connect(broker_host: str = "localhost", broker_port: int = 1883,
                         username: str = "", password: str = "",
                         device_name: str = "JARVIS-Desktop",
                         device_type: str = "desktop") -> dict:
    """Conecta ao broker MQTT. device_type: desktop, android, ios, server."""
    async def _connect():
        bridge = get_mqtt_bridge()
        bridge.broker_host = broker_host
        bridge.broker_port = broker_port
        bridge.username = username
        bridge.password = password

        dtype = DeviceType(device_type.lower())
        device_id = f"jarvis-{device_type}-{uuid.uuid4().hex[:8]}"

        caps = ["voice", "desktop_control", "file_ops", "system_admin"]
        if dtype == DeviceType.ANDROID:
            caps = ["voice", "android_control", "termux", "sensors"]

        success = await bridge.connect(device_id, device_name, dtype, caps)
        return {"success": success, "device_id": device_id, "broker": f"{broker_host}:{broker_port}"}

    return asyncio.run(_connect())


@tool(description="Envia comando para outro dispositivo JARVIS conectado.", category=ToolCategory.SYSTEM)
def cross_device_send_command(target_device: str, command: str, args: dict = None) -> dict:
    """Envia comando para device específico (use device_id ou 'broadcast')."""
    async def _send():
        bridge = get_mqtt_bridge()
        if target_device == "broadcast":
            return await bridge.broadcast(command, args)
        return await bridge.send_command(target_device, command, args)

    return asyncio.run(_send())


@tool(description="Lista dispositivos JARVIS conectados na rede.", category=ToolCategory.SYSTEM)
def cross_device_list() -> dict:
    """Mostra todos dispositivos registrados e seus status."""
    registry = get_device_registry()
    devices = []
    for d in registry.devices.values():
        devices.append({
            "id": d.id,
            "name": d.name,
            "type": d.type.value,
            "status": d.status,
            "capabilities": d.capabilities,
            "last_seen": d.last_seen
        })
    return {"success": True, "count": len(devices), "devices": devices}


@tool(description="Sincroniza variável/estado entre dispositivos JARVIS.", category=ToolCategory.SYSTEM)
def cross_device_sync(key: str, value: str, target_device: str = "") -> dict:
    """Sincroniza estado (chave-valor) entre devices. target_device vazio = todos."""
    async def _sync():
        bridge = get_mqtt_bridge()
        return await bridge.sync_state(key, value, target_device)

    return asyncio.run(_sync())


@tool(description="Inicia heartbeat automático para manter presença na rede.", category=ToolCategory.SYSTEM)
def cross_device_heartbeat(interval_seconds: int = 30) -> dict:
    """Inicia envio periódico de heartbeat."""
    async def _heartbeat_loop():
        bridge = get_mqtt_bridge()
        while bridge.connected:
            await bridge.send_heartbeat()
            await asyncio.sleep(interval_seconds)

    asyncio.create_task(_heartbeat_loop())
    return {"success": True, "message": f"Heartbeat iniciado ({interval_seconds}s)"}


@tool(description="Desconecta do broker MQTT.", category=ToolCategory.SYSTEM)
def cross_device_disconnect() -> dict:
    """Desconecta do broker."""
    bridge = get_mqtt_bridge()
    bridge.disconnect()
    return {"success": True, "message": "Desconectado"}


# ==================== EXPORT ====================

AVAILABLE_FUNCTIONS = {
    "cross_device_connect": cross_device_connect,
    "cross_device_send_command": cross_device_send_command,
    "cross_device_list": cross_device_list,
    "cross_device_sync": cross_device_sync,
    "cross_device_heartbeat": cross_device_heartbeat,
    "cross_device_disconnect": cross_device_disconnect,
}