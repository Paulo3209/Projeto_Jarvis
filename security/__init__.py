"""
Security Module - Authentication, authorization, and audit for JARVIS.
Includes credential management, device registry, and tamper-evident audit logging.
"""
from .authentication import (
    CredentialManager,
    JWTManager,
    APIKeyManager,
    SessionManager,
    get_credential_manager,
    get_jwt_manager,
    get_api_key_manager,
    get_session_manager,
    auth_store_credential,
    auth_get_credential,
    auth_list_credentials,
    auth_delete_credential,
    auth_create_jwt,
    auth_verify_jwt,
    auth_generate_api_key,
    auth_validate_api_key,
    auth_create_session,
    auth_validate_session,
    auth_revoke_session,
)

from .device_registry import (
    SecureDeviceRegistry,
    SecureDevice,
    get_secure_device_registry,
    secure_device_register,
    secure_device_list,
    secure_device_get,
    secure_device_block,
    secure_device_unblock,
    secure_device_set_trusted,
    secure_device_access_log,
)

from .audit import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    TamperEvidentLog,
    get_audit_logger,
    audit_log,
    audit_query,
    audit_verify,
    audit_stats,
)

__all__ = [
    # Authentication
    "CredentialManager",
    "JWTManager",
    "APIKeyManager",
    "SessionManager",
    "get_credential_manager",
    "get_jwt_manager",
    "get_api_key_manager",
    "get_session_manager",
    "auth_store_credential",
    "auth_get_credential",
    "auth_list_credentials",
    "auth_delete_credential",
    "auth_create_jwt",
    "auth_verify_jwt",
    "auth_generate_api_key",
    "auth_validate_api_key",
    "auth_create_session",
    "auth_validate_session",
    "auth_revoke_session",

    # Device Registry
    "SecureDeviceRegistry",
    "SecureDevice",
    "get_secure_device_registry",
    "secure_device_register",
    "secure_device_list",
    "secure_device_get",
    "secure_device_block",
    "secure_device_unblock",
    "secure_device_set_trusted",
    "secure_device_access_log",

    # Audit
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "AuditSeverity",
    "TamperEvidentLog",
    "get_audit_logger",
    "audit_log",
    "audit_query",
    "audit_verify",
    "audit_stats",
]