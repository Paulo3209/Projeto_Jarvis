"""
Android App Tools - Tools for Flutter/Android app integration.
"""
from core.plugin_system import tool, ToolCategory


@tool(
    description="Inicia o bridge de comunicação com app Android.",
    category=ToolCategory.SYSTEM,
)
async def android_bridge_start(host: str = "0.0.0.0", port: int = 8765, auth_required: bool = True) -> dict:
    """Inicia servidor WebSocket para app Android.

    Args:
        host: Host para escutar
        port: Porta para escutar
        auth_required: Exigir autenticação
    """
    from android_app.bridge import AndroidBridge, AndroidConfig, get_android_bridge

    config = AndroidConfig(host=host, port=port, auth_required=auth_required)
    bridge = AndroidBridge(config)
    await bridge.initialize()
    return {"success": True, "message": f"Android bridge iniciado em {host}:{port}"}


@tool(
    description="Para o bridge de comunicação com app Android.",
    category=ToolCategory.SYSTEM,
)
async def android_bridge_stop() -> dict:
    """Para o servidor WebSocket do app Android."""
    from android_app.bridge import _android_bridge
    if _android_bridge:
        await _android_bridge.shutdown()
        return {"success": True, "message": "Android bridge parado"}
    return {"success": False, "error": "Bridge não estava rodando"}


@tool(
    description="Envia notificação push para app Android.",
    category=ToolCategory.SYSTEM,
)
async def android_send_notification(
    title: str,
    body: str,
    notification_type: str = "info",
    client_id: str = None,
    data: dict = None,
    priority: int = 2
) -> dict:
    """Envia notificação para app Android conectado.

    Args:
        title: Título da notificação
        body: Corpo da notificação
        notification_type: Tipo (info, success, warning, error, command_result, device_alert, security_alert)
        client_id: ID do cliente específico (opcional, broadcast se não informado)
        data: Dados extras
        priority: Prioridade (1=baixa, 2=normal, 3=alta, 4=urgente)
    """
    from android_app.notifications import send_notification, NotificationType

    try:
        ntype = NotificationType(notification_type)
    except ValueError:
        ntype = NotificationType.INFO

    return await send_notification(title, body, ntype, client_id, data, priority)


@tool(
    description="Lista clientes Android conectados.",
    category=ToolCategory.SYSTEM,
)
async def android_list_clients() -> dict:
    """Lista todos os clientes Android conectados."""
    from android_app.bridge import _android_bridge
    if _android_bridge:
        return {"success": True, "clients": _android_bridge.get_connected_clients()}
    return {"success": False, "error": "Bridge não inicializado"}


@tool(
    description="Broadcast evento para todos os apps Android conectados.",
    category=ToolCategory.SYSTEM,
)
async def android_broadcast_event(event_type: str, data: dict) -> dict:
    """Envia evento para todos os clientes Android.

    Args:
        event_type: Tipo do evento
        data: Dados do evento
    """
    from android_app.bridge import _android_bridge
    if _android_bridge:
        await _android_bridge.broadcast_event(event_type, data)
        return {"success": True, "message": f"Evento {event_type} enviado"}
    return {"success": False, "error": "Bridge não inicializado"}


@tool(
    description="Executa comando no dispositivo via app Android.",
    category=ToolCategory.SYSTEM,
)
async def android_execute_command(
    command: str,
    params: dict = None,
    target_client: str = None
) -> dict:
    """Executa comando remoto via app Android.

    Args:
        command: Comando a executar (ping, get_status, execute_tool, get_devices, device_command, get_screen, voice_command)
        params: Parâmetros do comando
        target_client: ID do cliente alvo (opcional)
    """
    from android_app.commands import handle_mobile_command, CommandType

    try:
        cmd_type = CommandType(command)
    except ValueError:
        return {"success": False, "error": f"Comando desconhecido: {command}"}

    return await handle_mobile_command(cmd_type.value, params or {}, target_client or "android_app")


# ===== Dispositivo Android (App como agente) =====

@tool(
    description="Inicia agente JARVIS no dispositivo Android.",
    category=ToolCategory.SYSTEM,
)
async def android_agent_start(
    controller_host: str = "192.168.1.100",
    controller_port: int = 8766,
    device_name: str = "",
    auth_token: str = None
) -> dict:
    """Inicia agente JARVIS no Android.

    Args:
        controller_host: IP do controlador JARVIS
        controller_port: Porta do controlador
        device_name: Nome do dispositivo
        auth_token: Token de autenticação
    """
    from device_network.agent import NetworkAgent, AgentConfig, run_agent

    config = AgentConfig(
        controller_host=controller_host,
        controller_port=controller_port,
        device_name=device_name or "Android Device",
        device_type="phone",
        auth_token=auth_token,
    )

    agent = await run_agent(config)
    return {"success": True, "message": "Agente Android iniciado", "device_id": agent.config.device_id}


@tool(
    description="Para agente JARVIS no dispositivo Android.",
    category=ToolCategory.SYSTEM,
)
async def android_agent_stop() -> dict:
    """Para o agente JARVIS no Android."""
    # Em produção, manteria referência global
    return {"success": True, "message": "Comando de parada enviado"}


__all__ = [
    "android_bridge_start",
    "android_bridge_stop",
    "android_send_notification",
    "android_list_clients",
    "android_broadcast_event",
    "android_execute_command",
    "android_agent_start",
    "android_agent_stop",
]