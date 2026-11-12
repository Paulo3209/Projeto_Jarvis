"""
Device Tools - Device management tools for JARVIS.
Registers device discovery, connection, and control functions as tools.
"""
from core.plugin_system import tool, ToolCategory
from devices.manager import (
    get_device_manager,
    Device,
    DeviceType,
    DeviceStatus,
    ConnectionProtocol,
    DeviceCapability,
)
from devices.discovery import (
    DeviceDiscovery,
    discover_devices,
)
from devices.network import get_network_manager
from devices.bluetooth import get_bluetooth_manager
from devices.android import get_adb_manager
from devices.smart_home import get_smart_home_manager


# ===== Device Manager Tools =====

@tool(
    description="Lista todos os dispositivos registrados.",
    category=ToolCategory.SYSTEM,
)
async def list_devices(device_type: str = None, status: str = None, trusted_only: bool = False) -> dict:
    """Lista todos os dispositivos registrados no JARVIS.

    Args:
        device_type: Filtrar por tipo (computer, android, smart_tv, speaker, light, camera, router, sensor, actuator, home_assistant, unknown)
        status: Filtrar por status (discovered, authenticating, connected, disconnected, error, blocked)
        trusted_only: Mostrar apenas dispositivos confiáveis
    """
    manager = get_device_manager()

    dtype = DeviceType(device_type) if device_type else None
    dstatus = DeviceStatus(status) if status else None

    devices = manager.list_devices(device_type=dtype, status=dstatus, trusted_only=trusted_only)

    return {
        "success": True,
        "devices": [d.to_dict() for d in devices]
    }


@tool(
    description="Obtém detalhes de um dispositivo específico.",
    category=ToolCategory.SYSTEM,
)
async def get_device(device_id: str) -> dict:
    """Obtém detalhes completos de um dispositivo pelo ID.

    Args:
        device_id: ID do dispositivo
    """
    manager = get_device_manager()
    device = manager.get_device(device_id)

    if not device:
        return {"success": False, "error": "Dispositivo não encontrado"}

    return {"success": True, "device": device.to_dict()}


@tool(
    description="Conecta a um dispositivo registrado.",
    category=ToolCategory.SYSTEM,
)
async def connect_device(device_id: str, auth_data: dict = None) -> dict:
    """Conecta a um dispositivo registrado.

    Args:
        device_id: ID do dispositivo
        auth_data: Dados de autenticação (senha, token, etc.)
    """
    manager = get_device_manager()
    success = await manager.connect_device(device_id, auth_data or {})
    return {"success": success, "device_id": device_id}


@tool(
    description="Desconecta de um dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def disconnect_device(device_id: str) -> dict:
    """Desconecta de um dispositivo.

    Args:
        device_id: ID do dispositivo
    """
    manager = get_device_manager()
    success = await manager.disconnect_device(device_id)
    return {"success": success, "device_id": device_id}


@tool(
    description="Executa um comando em um dispositivo conectado.",
    category=ToolCategory.SYSTEM,
)
async def execute_device_command(device_id: str, command: str, parameters: dict = None, require_confirmation: bool = False) -> dict:
    """Executa um comando em um dispositivo conectado.

    Args:
        device_id: ID do dispositivo
        command: Nome do comando
        parameters: Parâmetros do comando
        require_confirmation: Se deve exigir confirmação
    """
    manager = get_device_manager()
    result = await manager.execute_command(device_id, command, parameters or {}, require_confirmation)
    return result


@tool(
    description="Registra um novo dispositivo descoberto manualmente.",
    category=ToolCategory.SYSTEM,
)
async def register_device(
    name: str,
    device_type: str,
    protocol: str,
    address: str,
    port: int = None,
    metadata: dict = None,
    capabilities: list = None
) -> dict:
    """Registra um novo dispositivo manualmente.

    Args:
        name: Nome do dispositivo
        device_type: Tipo (computer, android, smart_tv, speaker, light, camera, router, sensor, actuator, home_assistant, unknown)
        protocol: Protocolo (adb, ssh, http, https, mqtt, websocket, bluetooth, onvif, matter, home_assistant, custom)
        address: Endereço (IP, MAC, serial ADB, etc.)
        port: Porta (opcional)
        metadata: Metadados adicionais (fabricante, modelo, etc.)
        capabilities: Lista de capacidades
    """
    manager = get_device_manager()

    dtype = DeviceType(device_type)
    proto = ConnectionProtocol(protocol)

    caps = []
    if capabilities:
        for cap in capabilities:
            caps.append(DeviceCapability(**cap))

    device = manager.register_discovered_device(
        name=name,
        device_type=dtype,
        protocol=proto,
        address=address,
        port=port,
        metadata=metadata or {},
        capabilities=caps
    )

    return {"success": True, "device": device.to_dict()}


@tool(
    description="Define um dispositivo como confiável/não confiável.",
    category=ToolCategory.SYSTEM,
)
async def set_device_trusted(device_id: str, trusted: bool) -> dict:
    """Define se um dispositivo é confiável.

    Args:
        device_id: ID do dispositivo
        trusted: True para confiar, False para não confiar
    """
    manager = get_device_manager()
    success = manager.registry.set_trusted(device_id, trusted)
    return {"success": success, "device_id": device_id, "trusted": trusted}


@tool(
    description="Concede ou revoga permissão a um dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def device_permission(device_id: str, permission: str, grant: bool = True) -> dict:
    """Concede ou revoga uma permissão a um dispositivo.

    Args:
        device_id: ID do dispositivo
        permission: Nome da permissão
        grant: True para conceder, False para revogar
    """
    manager = get_device_manager()
    if grant:
        success = manager.registry.grant_permission(device_id, permission)
    else:
        success = manager.registry.revoke_permission(device_id, permission)
    return {"success": success, "device_id": device_id, "permission": permission, "granted": grant}


# ===== Device Discovery Tools =====

@tool(
    description="Inicia descoberta de dispositivos na rede e Bluetooth.",
    category=ToolCategory.SYSTEM,
)
async def start_device_discovery(
    enable_network: bool = True,
    enable_bluetooth: bool = True,
    network_interval: int = 60,
    bluetooth_interval: int = 30,
    network_range: str = None
) -> dict:
    """Inicia descoberta contínua de dispositivos.

    Args:
        enable_network: Habilitar descoberta de rede (mDNS + port scan)
        enable_bluetooth: Habilitar descoberta Bluetooth LE
        network_interval: Intervalo de varredura de rede em segundos
        bluetooth_interval: Intervalo de varredura Bluetooth em segundos
        network_range: Range de rede CIDR (ex: 192.168.1.0/24)
    """
    global _discovery_instance
    discovery = DeviceDiscovery()
    await discovery.start(
        enable_network=enable_network,
        enable_bluetooth=enable_bluetooth,
        network_interval=network_interval,
        bluetooth_interval=bluetooth_interval,
        network_range=network_range
    )
    _discovery_instance = discovery
    return {"success": True, "message": "Descoberta iniciada"}


@tool(
    description="Para a descoberta de dispositivos.",
    category=ToolCategory.SYSTEM,
)
async def stop_device_discovery() -> dict:
    """Para a descoberta contínua de dispositivos."""
    global _discovery_instance
    if '_discovery_instance' in globals() and _discovery_instance:
        await _discovery_instance.stop()
        _discovery_instance = None
        return {"success": True, "message": "Descoberta parada"}
    return {"success": False, "error": "Descoberta não estava rodando"}


@tool(
    description="Faz uma varredura única de dispositivos.",
    category=ToolCategory.SYSTEM,
)
async def scan_devices_once(
    enable_network: bool = True,
    enable_bluetooth: bool = True,
    timeout: int = 15
) -> dict:
    """Faz uma varredura única e retorna dispositivos encontrados.

    Args:
        enable_network: Incluir varredura de rede
        enable_bluetooth: Incluir varredura Bluetooth
        timeout: Tempo máximo de espera em segundos
    """
    results = await discover_devices(
        enable_network=enable_network,
        enable_bluetooth=enable_bluetooth,
        timeout=timeout
    )
    return {
        "success": True,
        "devices_found": len(results),
        "devices": [
            {
                "name": d.name,
                "type": d.device_type.value,
                "protocol": d.protocol.value,
                "address": d.address,
                "port": d.port,
                "metadata": d.metadata,
                "rssi": d.rssi
            }
            for d in results
        ]
    }


# ===== Network Manager Tools =====

@tool(
    description="Faz requisição HTTP a um dispositivo de rede.",
    category=ToolCategory.WEB,
)
async def network_http_request(
    device_id: str,
    method: str,
    path: str,
    data: dict = None,
    params: dict = None
) -> dict:
    """Faz requisição HTTP/REST a um dispositivo configurado.

    Args:
        device_id: ID do dispositivo
        method: Método HTTP (GET, POST, PUT, DELETE, PATCH)
        path: Caminho da API
        data: Corpo da requisição (JSON)
        params: Query parameters
    """
    manager = get_network_manager()
    return await manager.http_request(device_id, method, path, data, params)


@tool(
    description="Executa comando SSH em dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def network_ssh_exec(device_id: str, command: str) -> dict:
    """Executa comando via SSH.

    Args:
        device_id: ID do dispositivo
        command: Comando a executar
    """
    manager = get_network_manager()
    return await manager.ssh_exec(device_id, command)


@tool(
    description="Publica mensagem MQTT.",
    category=ToolCategory.SYSTEM,
)
async def network_mqtt_publish(device_id: str, topic: str, payload: dict, qos: int = 0) -> dict:
    """Publica mensagem em tópico MQTT.

    Args:
        device_id: ID do dispositivo (broker MQTT)
        topic: Tópico MQTT
        payload: Payload como dict
        qos: Quality of Service (0, 1, 2)
    """
    manager = get_network_manager()
    return await manager.mqtt_publish(device_id, topic, payload, qos)


@tool(
    description="Chama serviço Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def network_hass_call_service(
    device_id: str,
    domain: str,
    service: str,
    service_data: dict = None,
    target: dict = None
) -> dict:
    """Chama um serviço no Home Assistant.

    Args:
        device_id: ID do dispositivo Home Assistant
        domain: Domínio (light, switch, climate, etc.)
        service: Nome do serviço (turn_on, turn_off, set_temperature, etc.)
        service_data: Dados do serviço
        target: Entidades alvo
    """
    manager = get_network_manager()
    return await manager.hass_call_service(device_id, domain, service, service_data, target)


# ===== Bluetooth Tools =====

@tool(
    description="Conecta a dispositivo Bluetooth LE.",
    category=ToolCategory.SYSTEM,
)
async def ble_connect(address: str, timeout: float = 10.0) -> dict:
    """Conecta a um dispositivo Bluetooth LE.

    Args:
        address: Endereço MAC do dispositivo
        timeout: Timeout de conexão em segundos
    """
    from devices.bluetooth import ble_connect as _ble_connect
    return await _ble_connect(address, timeout)


@tool(
    description="Lê característica BLE.",
    category=ToolCategory.SYSTEM,
)
async def ble_read(address: str, characteristic_uuid: str) -> dict:
    """Lê valor de uma característica BLE.

    Args:
        address: Endereço MAC do dispositivo
        characteristic_uuid: UUID da característica
    """
    from devices.bluetooth import ble_read as _ble_read
    return await _ble_read(address, characteristic_uuid)


@tool(
    description="Escreve em característica BLE.",
    category=ToolCategory.SYSTEM,
)
async def ble_write(address: str, characteristic_uuid: str, data_hex: str, response: bool = True) -> dict:
    """Escreve valor em uma característica BLE.

    Args:
        address: Endereço MAC do dispositivo
        characteristic_uuid: UUID da característica
        data_hex: Dados em hexadecimal
        response: Se deve aguardar resposta
    """
    from devices.bluetooth import ble_write as _ble_write
    return await _ble_write(address, characteristic_uuid, data_hex, response)


@tool(
    description="Lê sensor BLE padrão.",
    category=ToolCategory.SYSTEM,
)
async def ble_read_sensor(address: str, sensor_type: str) -> dict:
    """Lê dados de sensor BLE padrão (heart_rate, battery, temperature, humidity, pressure).

    Args:
        address: Endereço MAC do dispositivo
        sensor_type: Tipo de sensor (heart_rate, battery, temperature, humidity, pressure)
    """
    from devices.bluetooth import ble_read_sensor as _ble_read_sensor
    return await _ble_read_sensor(address, sensor_type)


@tool(
    description="Descobre serviços GATT de dispositivo BLE.",
    category=ToolCategory.SYSTEM,
)
async def ble_discover_services(address: str) -> dict:
    """Descobre todos os serviços e características GATT.

    Args:
        address: Endereço MAC do dispositivo
    """
    from devices.bluetooth import ble_discover_services as _ble_discover_services
    return await _ble_discover_services(address)


# ===== Android ADB Tools =====

@tool(
    description="Lista dispositivos Android conectados via ADB.",
    category=ToolCategory.SYSTEM,
)
async def adb_list_devices() -> dict:
    """Lista todos os dispositivos Android conectados via ADB."""
    from devices.android import adb_list_devices as _adb_list_devices
    return await _adb_list_devices()


@tool(
    description="Executa comando shell no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_shell(serial: str, command: str) -> dict:
    """Executa comando shell no dispositivo Android.

    Args:
        serial: Serial do dispositivo
        command: Comando shell
    """
    from devices.android import adb_shell as _adb_shell
    return await _adb_shell(serial, command)


@tool(
    description="Instala APK no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_install(serial: str, apk_path: str) -> dict:
    """Instala APK no dispositivo Android.

    Args:
        serial: Serial do dispositivo
        apk_path: Caminho local do APK
    """
    from devices.android import adb_install as _adb_install
    return await _adb_install(serial, apk_path)


@tool(
    description="Desinstala app do Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_uninstall(serial: str, package_name: str) -> dict:
    """Desinstala app do dispositivo Android.

    Args:
        serial: Serial do dispositivo
        package_name: Nome do pacote
    """
    from devices.android import adb_uninstall as _adb_uninstall
    return await _adb_uninstall(serial, package_name)


@tool(
    description="Captura tela do Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_screencap(serial: str, local_path: str = None) -> dict:
    """Captura screenshot do dispositivo Android.

    Args:
        serial: Serial do dispositivo
        local_path: Caminho local para salvar (opcional)
    """
    from devices.android import adb_screencap as _adb_screencap
    return await _adb_screencap(serial, local_path)


@tool(
    description="Simula toque na tela do Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_input_tap(serial: str, x: int, y: int) -> dict:
    """Simula toque nas coordenadas.

    Args:
        serial: Serial do dispositivo
        x: Coordenada X
        y: Coordenada Y
    """
    from devices.android import adb_input_tap as _adb_input_tap
    return await _adb_input_tap(serial, x, y)


@tool(
    description="Simula deslize na tela do Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_input_swipe(serial: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> dict:
    """Simula gesto de deslize.

    Args:
        serial: Serial do dispositivo
        x1: X inicial
        y1: Y inicial
        x2: X final
        y2: Y final
        duration: Duração em ms
    """
    from devices.android import adb_input_swipe as _adb_input_swipe
    return await _adb_input_swipe(serial, x1, y1, x2, y2, duration)


@tool(
    description="Digita texto no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_input_text(serial: str, text: str) -> dict:
    """Digita texto no dispositivo Android.

    Args:
        serial: Serial do dispositivo
        text: Texto a digitar
    """
    from devices.android import adb_input_text as _adb_input_text
    return await _adb_input_text(serial, text)


@tool(
    description="Envia evento de tecla no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_input_key(serial: str, keycode: int) -> dict:
    """Envia keycode para o Android.

    Args:
        serial: Serial do dispositivo
        keycode: Código da tecla (ex: 3=HOME, 4=BACK, 66=ENTER, 24=VOL_UP, 25=VOL_DOWN)
    """
    from devices.android import adb_input_key as _adb_input_key
    return await _adb_input_key(serial, keycode)


@tool(
    description="Inicia app no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_start_app(serial: str, package_name: str, activity: str = None) -> dict:
    """Inicia aplicativo no Android.

    Args:
        serial: Serial do dispositivo
        package_name: Nome do pacote
        activity: Activity específica (opcional)
    """
    from devices.android import adb_start_app as _adb_start_app
    return await _adb_start_app(serial, package_name, activity)


@tool(
    description="Para app no Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_stop_app(serial: str, package_name: str) -> dict:
    """Para (force stop) aplicativo no Android.

    Args:
        serial: Serial do dispositivo
        package_name: Nome do pacote
    """
    from devices.android import adb_stop_app as _adb_stop_app
    return await _adb_stop_app(serial, package_name)


@tool(
    description="Obtém info de bateria do Android.",
    category=ToolCategory.SYSTEM,
)
async def adb_get_battery(serial: str) -> dict:
    """Obtém informações de bateria do dispositivo Android.

    Args:
        serial: Serial do dispositivo
    """
    from devices.android import adb_get_battery as _adb_get_battery
    return await _adb_get_battery(serial)


# ===== Smart Home Tools =====

@tool(
    description="Obtém todos os estados do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_get_states(device_id: str) -> dict:
    """Obtém todos os estados das entidades do Home Assistant.

    Args:
        device_id: ID do dispositivo Home Assistant
    """
    manager = get_smart_home_manager()
    entities = await manager.hass_get_states(device_id)
    return {
        "success": True,
        "entities": [
            {
                "entity_id": e.entity_id,
                "domain": e.domain,
                "state": e.state,
                "attributes": e.attributes,
                "friendly_name": e.friendly_name,
                "device_class": e.device_class,
                "unit_of_measurement": e.unit_of_measurement
            }
            for e in entities
        ]
    }


@tool(
    description="Obtém estado de uma entidade do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_get_state(device_id: str, entity_id: str) -> dict:
    """Obtém estado de uma entidade específica.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID da entidade (ex: light.sala, switch.quarto)
    """
    manager = get_smart_home_manager()
    entity = await manager.hass_get_state(device_id, entity_id)
    if entity:
        return {
            "success": True,
            "entity": {
                "entity_id": entity.entity_id,
                "domain": entity.domain,
                "state": entity.state,
                "attributes": entity.attributes,
                "friendly_name": entity.friendly_name,
                "device_class": entity.device_class,
                "unit_of_measurement": entity.unit_of_measurement
            }
        }
    return {"success": False, "error": "Entidade não encontrada"}


@tool(
    description="Liga entidade do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_turn_on(device_id: str, entity_id: str, **kwargs) -> dict:
    """Liga uma entidade (light, switch, fan, etc.).

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID da entidade
        **kwargs: Parâmetros adicionais (brightness, color, etc.)
    """
    manager = get_smart_home_manager()
    return await manager.hass_turn_on(device_id, entity_id, **kwargs)


@tool(
    description="Desliga entidade do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_turn_off(device_id: str, entity_id: str) -> dict:
    """Desliga uma entidade.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID da entidade
    """
    manager = get_smart_home_manager()
    return await manager.hass_turn_off(device_id, entity_id)


@tool(
    description="Alterna estado de entidade do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_toggle(device_id: str, entity_id: str) -> dict:
    """Alterna estado de uma entidade.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID da entidade
    """
    manager = get_smart_home_manager()
    return await manager.hass_toggle(device_id, entity_id)


@tool(
    description="Controla luz do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_set_light(
    device_id: str,
    entity_id: str,
    brightness: int = None,
    color_temp: int = None,
    rgb_color: list = None,
    hs_color: list = None,
    xy_color: list = None,
    transition: float = None
) -> dict:
    """Controla luz com parâmetros avançados.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID da luz (ex: light.sala)
        brightness: Brilho 0-255
        color_temp: Temperatura de cor (mireds)
        rgb_color: Cor RGB [r, g, b] 0-255
        hs_color: Cor HSV [h, s] 0-360, 0-100
        xy_color: Cor XY [x, y] 0-1
        transition: Transição em segundos
    """
    manager = get_smart_home_manager()
    return await manager.hass_set_light(
        device_id, entity_id,
        brightness=brightness,
        color_temp=color_temp,
        rgb_color=rgb_color,
        hs_color=hs_color,
        xy_color=xy_color,
        transition=transition
    )


@tool(
    description="Controla clima do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_set_climate(
    device_id: str,
    entity_id: str,
    temperature: float = None,
    target_temp_low: float = None,
    target_temp_high: float = None,
    hvac_mode: str = None,
    preset_mode: str = None,
    fan_mode: str = None
) -> dict:
    """Controla termostato/climate.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID do climate (ex: climate.sala)
        temperature: Temperatura alvo
        target_temp_low: Temp. baixa (modo range)
        target_temp_high: Temp. alta (modo range)
        hvac_mode: Modo (heat, cool, heat_cool, off, auto, fan_only, dry)
        preset_mode: Preset (none, eco, away, boost, comfort, home, sleep, activity)
        fan_mode: Modo ventilador (auto, low, medium, high, etc.)
    """
    manager = get_smart_home_manager()
    return await manager.hass_set_climate(
        device_id, entity_id,
        temperature=temperature,
        target_temp_low=target_temp_low,
        target_temp_high=target_temp_high,
        hvac_mode=hvac_mode,
        preset_mode=preset_mode,
        fan_mode=fan_mode
    )


@tool(
    description="Controla cortina/porta do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_set_cover(device_id: str, entity_id: str, position: int = None, tilt_position: int = None) -> dict:
    """Controla cover (cortina, porta, portão).

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID do cover (ex: cover.cortina_sala)
        position: Posição 0-100 (0=fechado, 100=aberto)
        tilt_position: Inclinação 0-100 (para persianas)
    """
    manager = get_smart_home_manager()
    return await manager.hass_set_cover(device_id, entity_id, position=position, tilt_position=tilt_position)


@tool(
    description="Controla mídia do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_media_control(device_id: str, entity_id: str, action: str, volume_level: float = None) -> dict:
    """Controla media_player.

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID do media_player
        action: Ação (play, pause, stop, volume)
        volume_level: Volume 0.0-1.0 (para action=volume)
    """
    manager = get_smart_home_manager()

    if action == "play":
        return await manager.hass_media_play(device_id, entity_id)
    elif action == "pause":
        return await manager.hass_media_pause(device_id, entity_id)
    elif action == "stop":
        return await manager.hass_media_stop(device_id, entity_id)
    elif action == "volume":
        if volume_level is None:
            return {"success": False, "error": "volume_level required for volume action"}
        return await manager.hass_media_volume(device_id, entity_id, volume_level)
    else:
        return {"success": False, "error": f"Unknown action: {action}"}


@tool(
    description="Trava/destranca fechadura do Home Assistant.",
    category=ToolCategory.SYSTEM,
)
async def hass_lock_control(device_id: str, entity_id: str, action: str) -> dict:
    """Controla lock (fechadura).

    Args:
        device_id: ID do dispositivo Home Assistant
        entity_id: ID do lock
        action: lock ou unlock
    """
    manager = get_smart_home_manager()

    if action == "lock":
        return await manager.hass_lock(device_id, entity_id)
    elif action == "unlock":
        return await manager.hass_unlock(device_id, entity_id)
    else:
        return {"success": False, "error": f"Unknown action: {action}"}


# Global discovery instance
_discovery_instance = None