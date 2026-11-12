"""
Security Tools - Authentication, device registry, and audit tools for JARVIS.
"""
from core.plugin_system import tool, ToolCategory


# ===== Authentication Tools =====

@tool(
    description="Armazena credencial de forma segura (criptografada).",
    category=ToolCategory.SYSTEM,
)
async def auth_store_credential(
    name: str,
    value: str,
    cred_type: str = "api_key",
    metadata: dict = None,
    expires_days: int = None,
    tags: list = None
) -> dict:
    """Armazena credencial segura.

    Args:
        name: Nome identificador
        value: Valor da credencial (senha, token, chave)
        cred_type: Tipo (api_key, token, password, certificate)
        metadata: Metadados adicionais
        expires_days: Dias até expirar
        tags: Tags para organização
    """
    from security.authentication import auth_store_credential as _auth_store_credential
    return await _auth_store_credential(name, value, cred_type, metadata, expires_days, tags)


@tool(
    description="Recupera credencial armazenada.",
    category=ToolCategory.SYSTEM,
)
async def auth_get_credential(credential_id: str = None, name: str = None) -> dict:
    """Recupera valor de credencial.

    Args:
        credential_id: ID da credencial
        name: Nome da credencial (alternativa ao ID)
    """
    from security.authentication import auth_get_credential as _auth_get_credential
    return await _auth_get_credential(credential_id, name)


@tool(
    description="Lista credenciais armazenadas.",
    category=ToolCategory.SYSTEM,
)
async def auth_list_credentials(cred_type: str = None, tags: list = None) -> dict:
    """Lista credenciais (sem mostrar valores).

    Args:
        cred_type: Filtrar por tipo
        tags: Filtrar por tags
    """
    from security.authentication import auth_list_credentials as _auth_list_credentials
    return await _auth_list_credentials(cred_type, tags)


@tool(
    description="Remove credencial armazenada.",
    category=ToolCategory.SYSTEM,
)
async def auth_delete_credential(credential_id: str) -> dict:
    """Remove credencial.

    Args:
        credential_id: ID da credencial
    """
    from security.authentication import auth_delete_credential as _auth_delete_credential
    return await _auth_delete_credential(credential_id)


@tool(
    description="Cria token JWT.",
    category=ToolCategory.SYSTEM,
)
async def auth_create_jwt(subject: str, scopes: list = None, expires_in: int = 3600, extra: dict = None) -> dict:
    """Cria token JWT.

    Args:
        subject: Assunto do token (user ID, service name)
        scopes: Escopos/permissões
        expires_in: Expiração em segundos
        extra: Claims extras
    """
    from security.authentication import auth_create_jwt as _auth_create_jwt
    return await _auth_create_jwt(subject, scopes, expires_in, extra)


@tool(
    description="Verifica token JWT.",
    category=ToolCategory.SYSTEM,
)
async def auth_verify_jwt(token: str) -> dict:
    """Verifica e decodifica token JWT.

    Args:
        token: Token JWT
    """
    from security.authentication import auth_verify_jwt as _auth_verify_jwt
    return await _auth_verify_jwt(token)


@tool(
    description="Gera chave de API.",
    category=ToolCategory.SYSTEM,
)
async def auth_generate_api_key(name: str, scopes: list = None, expires_days: int = 365, rate_limit: int = 1000) -> dict:
    """Gera nova chave de API.

    Args:
        name: Nome da chave
        scopes: Escopos permitidos
        expires_days: Validade em dias
        rate_limit: Limite de requisições por hora
    """
    from security.authentication import auth_generate_api_key as _auth_generate_api_key
    return await _auth_generate_api_key(name, scopes, expires_days, rate_limit)


@tool(
    description="Valida chave de API.",
    category=ToolCategory.SYSTEM,
)
async def auth_validate_api_key(key_secret: str) -> dict:
    """Valida chave de API.

    Args:
        key_secret: Segredo da chave
    """
    from security.authentication import auth_validate_api_key as _auth_validate_api_key
    return await _auth_validate_api_key(key_secret)


@tool(
    description="Cria sessão de usuário.",
    category=ToolCategory.SYSTEM,
)
async def auth_create_session(user_id: str, metadata: dict = None, ttl: int = None) -> dict:
    """Cria sessão.

    Args:
        user_id: ID do usuário
        metadata: Dados da sessão
        ttl: Tempo de vida em segundos
    """
    from security.authentication import auth_create_session as _auth_create_session
    return await _auth_create_session(user_id, metadata, ttl)


@tool(
    description="Valida sessão de usuário.",
    category=ToolCategory.SYSTEM,
)
async def auth_validate_session(session_id: str) -> dict:
    """Valida sessão.

    Args:
        session_id: ID da sessão
    """
    from security.authentication import auth_validate_session as _auth_validate_session
    return await _auth_validate_session(session_id)


@tool(
    description="Revoga sessão.",
    category=ToolCategory.SYSTEM,
)
async def auth_revoke_session(session_id: str) -> dict:
    """Revoga sessão.

    Args:
        session_id: ID da sessão
    """
    from security.authentication import auth_revoke_session as _auth_revoke_session
    return await _auth_revoke_session(session_id)


# ===== Secure Device Registry Tools =====

@tool(
    description="Registra dispositivo no registro seguro.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_register(
    name: str,
    device_type: str,
    protocol: str,
    address: str,
    port: int = None,
    metadata: dict = None,
    capabilities: list = None,
    allowed_users: list = None,
    allowed_networks: list = None,
    security_level: int = 1,
    requires_mfa: bool = False
) -> dict:
    """Registra dispositivo com segurança.

    Args:
        name: Nome do dispositivo
        device_type: Tipo (computer, android, smart_tv, etc.)
        protocol: Protocolo (adb, ssh, http, bluetooth, etc.)
        address: Endereço (IP, MAC, serial)
        port: Porta
        metadata: Metadados
        capabilities: Capacidades
        allowed_users: Usuários permitidos
        allowed_networks: Redes permitidas (CIDR)
        security_level: Nível 1-4
        requires_mfa: Exigir MFA para comandos
    """
    from security.device_registry import secure_device_register as _secure_device_register
    return await _secure_device_register(
        name, device_type, protocol, address, port, metadata, capabilities,
        allowed_users, allowed_networks, security_level, requires_mfa
    )


@tool(
    description="Lista dispositivos do registro seguro.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_list(user: str = None, network: str = None) -> dict:
    """Lista dispositivos acessíveis.

    Args:
        user: Filtrar por usuário
        network: Filtrar por rede
    """
    from security.device_registry import secure_device_list as _secure_device_list
    return await _secure_device_list(user, network)


@tool(
    description="Obtém dispositivo do registro seguro.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_get(device_id: str) -> dict:
    """Obtém detalhes do dispositivo.

    Args:
        device_id: ID do dispositivo
    """
    from security.device_registry import secure_device_get as _secure_device_get
    return await _secure_device_get(device_id)


@tool(
    description="Bloqueia dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_block(device_id: str, reason: str, blocked_by: str = None) -> dict:
    """Bloqueia dispositivo.

    Args:
        device_id: ID do dispositivo
        reason: Motivo do bloqueio
        blocked_by: Quem bloqueou
    """
    from security.device_registry import secure_device_block as _secure_device_block
    return await _secure_device_block(device_id, reason, blocked_by)


@tool(
    description="Desbloqueia dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_unblock(device_id: str, unblocked_by: str = None) -> dict:
    """Desbloqueia dispositivo.

    Args:
        device_id: ID do dispositivo
        unblocked_by: Quem desbloqueou
    """
    from security.device_registry import secure_device_unblock as _secure_device_unblock
    return await _secure_device_unblock(device_id, unblocked_by)


@tool(
    description="Define confiança do dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_set_trusted(device_id: str, trusted: bool, approved_by: str = None) -> dict:
    """Define se dispositivo é confiável.

    Args:
        device_id: ID do dispositivo
        trusted: True/False
        approved_by: Quem aprovou
    """
    from security.device_registry import secure_device_set_trusted as _secure_device_set_trusted
    return await _secure_device_set_trusted(device_id, trusted, approved_by)


@tool(
    description="Consulta log de acesso do dispositivo.",
    category=ToolCategory.SYSTEM,
)
async def secure_device_access_log(device_id: str = None, limit: int = 100) -> dict:
    """Log de acesso.

    Args:
        device_id: ID do dispositivo (opcional)
        limit: Máximo de entradas
    """
    from security.device_registry import secure_device_access_log as _secure_device_access_log
    return await _secure_device_access_log(device_id, limit)


# ===== Audit Tools =====

@tool(
    description="Registra evento de auditoria.",
    category=ToolCategory.SYSTEM,
)
async def audit_log(
    event_type: str,
    user: str,
    source: str,
    action: str,
    result: str,
    details: dict = None,
    severity: str = None,
    tags: list = None,
    session_id: str = None
) -> dict:
    """Log de auditoria.

    Args:
        event_type: Tipo (login_success, tool_executed, device_command, etc.)
        user: Usuário
        source: Fonte (ferramenta, IP, componente)
        action: Ação realizada
        result: success, failure, partial
        details: Detalhes extras
        severity: info, warning, error, critical
        tags: Tags
        session_id: ID da sessão
    """
    from security.audit import audit_log as _audit_log
    return await _audit_log(event_type, user, source, action, result, details, severity, tags, session_id)


@tool(
    description="Consulta log de auditoria.",
    category=ToolCategory.SYSTEM,
)
async def audit_query(
    limit: int = 100,
    event_type: str = None,
    severity: str = None,
    user: str = None,
    hours: int = 24
) -> dict:
    """Consulta auditoria.

    Args:
        limit: Máximo de entradas
        event_type: Filtrar por tipo
        severity: Filtrar por severidade
        user: Filtrar por usuário
        hours: Últimas N horas
    """
    from security.audit import audit_query as _audit_query
    return await _audit_query(limit, event_type, severity, user, hours)


@tool(
    description="Verifica integridade do log de auditoria.",
    category=ToolCategory.SYSTEM,
)
async def audit_verify() -> dict:
    """Verifica integridade (hash chaining)."""
    from security.audit import audit_verify as _audit_verify
    return await _audit_verify()


@tool(
    description="Estatísticas de auditoria.",
    category=ToolCategory.SYSTEM,
)
async def audit_stats(hours: int = 24) -> dict:
    """Estatísticas de auditoria.

    Args:
        hours: Últimas N horas
    """
    from security.audit import audit_stats as _audit_stats
    return await _audit_stats(hours)