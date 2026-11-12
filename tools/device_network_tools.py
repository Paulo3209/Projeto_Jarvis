"""
Device Network Tools - Tools for managing distributed device network.
"""
from core.plugin_system import tool, ToolCategory


@tool(
    description="Inicia a rede de dispositivos JARVIS.",
    category=ToolCategory.SYSTEM,
)
async def device_network_start(
    controller_id: str = "",
    listen_port: int = 8766,
    max_agents: int = 50,
    auto_approve_trusted: bool = True
) -> dict:
    """Inicia gerenciador de rede de dispositivos.

    Args:
        controller_id: ID do controlador (auto-gerado se vazio)
        listen_port: Porta para conexões de agentes
        max_agents: Máximo de agentes simultâneos
        auto_approve_trusted: Aprovar automaticamente dispositivos confiáveis
    """
    from device_network.manager import DeviceNetworkManager, NetworkConfig, get_device_network

    config = NetworkConfig(
        controller_id=controller_id,
        listen_port=listen_port,
        max_agents=max_agents,
        auto_approve_trusted=auto_approve_trusted,
    )
    network = DeviceNetworkManager(config)
    await network.initialize()
    return {"success": True, "message": f"Rede de dispositivos iniciada em porta {listen_port}", "controller_id": config.controller_id}


@tool(
    description="Para a rede de dispositivos JARVIS.",
    category=ToolCategory.SYSTEM,
)
async def device_network_stop() -> dict:
    """Para o gerenciador de rede de dispositivos."""
    from device_network.manager import _device_network
    if _device_network:
        await _device_network.shutdown()
        return {"success": True, "message": "Rede de dispositivos parada"}
    return {"success": False, "error": "Rede não estava rodando"}


@tool(
    description="Lista dispositivos na rede.",
    category=ToolCategory.SYSTEM,
)
async def device_network_list(role: str = None, status: str = None) -> dict:
    """Lista dispositivos na rede.

    Args:
        role: Filtrar por papel (controller, agent, client, sensor, display)
        status: Filtrar por status (offline, online, busy, error, updating)
    """
    from device_network.manager import get_device_network, DeviceRole, DeviceStatus

    network = await get_device_network()
    role_enum = DeviceRole(role) if role else None
    status_enum = DeviceStatus(status) if status else None
    devices = network.list_devices(role_enum, status_enum)

    return {
        "success": True,
        "devices": [
            {
                "device_id": d.device_id,
                "name": d.name,
                "role": d.role.value,
                "device_type": d.device_type,
                "platform": d.platform,
                "status": d.status.value,
                "capabilities": d.capabilities,
                "address": d.address,
                "trusted": d.trusted,
                "last_seen": d.last_seen.isoformat(),
            }
            for d in devices
        ],
        "total": len(devices),
    }


@tool(
    description="Obtém detalhes de um dispositivo na rede.",
    category=ToolCategory.SYSTEM,
)
async def device_network_get(device_id: str) -> dict:
    """Obtém detalhes completos de um dispositivo.

    Args:
        device_id: ID do dispositivo
    """
    from device_network.manager import get_device_network

    network = await get_device_network()
    device = network.get_device(device_id)

    if not device:
        return {"success": False, "error": "Dispositivo não encontrado"}

    return {
        "success": True,
        "device": {
            "device_id": device.device_id,
            "name": device.name,
            "role": device.role.value,
            "device_type": device.device_type,
            "platform": device.platform,
            "capabilities": device.capabilities,
            "status": device.status.value,
            "address": device.address,
            "port": device.port,
            "last_seen": device.last_seen.isoformat(),
            "metadata": device.metadata,
            "trusted": device.trusted,
            "public_key": device.public_key,
            "assigned_tasks": device.assigned_tasks,
        }
    }


@tool(
    description="Envia comando para dispositivo na rede.",
    category=ToolCategory.SYSTEM,
)
async def device_network_command(device_id: str, command: str, params: dict = None) -> dict:
    """Envia comando para dispositivo específico.

    Args:
        device_id: ID do dispositivo alvo
        command: Comando a executar
        params: Parâmetros do comando
    """
    from device_network.manager import get_device_network

    network = await get_device_network()
    return await network.send_command(device_id, command, params or {})


@tool(
    description="Broadcast comando para múltiplos dispositivos.",
    category=ToolCategory.SYSTEM,
)
async def device_network_broadcast(command: str, params: dict = None, role: str = None) -> dict:
    """Envia comando para todos os dispositivos (ou por papel).

    Args:
        command: Comando a executar
        params: Parâmetros do comando
        role: Filtrar por papel (agent, sensor, display, etc.)
    """
    from device_network.manager import get_device_network, DeviceRole

    network = await get_device_network()
    role_enum = DeviceRole(role) if role else None
    return await network.broadcast_command(command, params or {}, role_enum)


@tool(
    description="Define dispositivo como confiável.",
    category=ToolCategory.SYSTEM,
)
async def device_network_trust(device_id: str, trusted: bool = True) -> dict:
    """Define confiança do dispositivo.

    Args:
        device_id: ID do dispositivo
        trusted: True para confiar, False para remover confiança
    """
    from device_network.manager import get_device_network

    network = await get_device_network()
    device = network.get_device(device_id)
    if not device:
        return {"success": False, "error": "Dispositivo não encontrado"}

    device.trusted = trusted
    return {"success": True, "message": f"Dispositivo {'marcado como confiável' if trusted else 'confiança removida'}"}


@tool(
    description="Inicia descoberta de dispositivos na rede.",
    category=ToolCategory.SYSTEM,
)
async def device_network_discover(
    enable_mdns: bool = True,
    enable_port_scan: bool = True,
    network_range: str = "192.168.1.0/24"
) -> dict:
    """Inicia descoberta de dispositivos JARVIS na rede.

    Args:
        enable_mdns: Usar mDNS/zeroconf
        enable_port_scan: Escanear portas conhecidas
        network_range: Range de rede para scan (CIDR)
    """
    from device_network.discovery import NetworkDiscovery, DiscoveryConfig

    config = DiscoveryConfig(
        enable_mdns=enable_mdns,
        enable_port_scan=enable_port_scan,
        network_range=network_range,
    )

    discovery = NetworkDiscovery(config)
    discovered = []

    def on_discover(device):
        discovered.append({
            "name": device.name,
            "address": device.address,
            "port": device.port,
            "device_id": device.device_id,
            "role": device.role,
            "device_type": device.device_type,
            "platform": device.platform,
        })

    discovery.add_callback(on_discover)
    await discovery.start()

    # Aguardar descoberta
    await asyncio.sleep(10)
    await discovery.stop()

    return {"success": True, "discovered": discovered, "count": len(discovered)}


@tool(
    description="Analisa topologia da rede de dispositivos.",
    category=ToolCategory.SYSTEM,
)
async def device_network_topology() -> dict:
    """Analisa topologia da rede (clusters, dispositivos centrais, isolados)."""
    from device_network.manager import get_device_network
    from device_network.discovery import get_device_visualizer

    network = await get_device_network()
    visualizer = get_device_visualizer()

    device_map = await visualizer.generate_map()
    topology = visualizer.analyze_topology(device_map)

    return {
        "success": True,
        "topology": {
            "clusters": topology.clusters,
            "central_devices": topology.central_devices,
            "isolated_devices": topology.isolated_devices,
            "topology_type": topology.topology_type,
            "diameter": topology.diameter,
            "avg_path_length": topology.avg_path_length,
            "density": topology.density,
        },
        "device_map": {
            "nodes": len(device_map.nodes),
            "links": len(device_map.links),
            "layout": device_map.layout.value,
        }
    }


@tool(
    description="Sincroniza estado com dispositivos.",
    category=ToolCategory.SYSTEM,
)
async def device_network_sync(device_id: str = None) -> dict:
    """Força sincronização de estado.

    Args:
        device_id: ID do dispositivo (None = todos)
    """
    from device_network.manager import get_device_network

    network = await get_device_network()

    if device_id:
        if hasattr(network, '_synchronizer'):
            await network._sync_manager.force_sync(device_id)
        return {"success": True, "message": f"Sincronização forçada com {device_id}"}
    else:
        if hasattr(network, '_sync_manager'):
            await network._sync_manager.force_sync()
        return {"success": True, "message": "Sincronização forçada com todos os dispositivos"}


__all__ = [
    "device_network_start",
    "device_network_stop",
    "device_network_list",
    "device_network_get",
    "device_network_command",
    "device_network_broadcast",
    "device_network_trust",
    "device_network_discover",
    "device_network_topology",
    "device_network_sync",
]