"""
Authentication Module - Secure authentication for JARVIS.
Handles API keys, tokens, JWT, and secure credential storage.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import jwt

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


@dataclass
class Credential:
    """Stored credential."""
    id: str
    name: str
    type: str  # api_key, token, password, certificate
    value: str  # Encrypted
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class AuthToken:
    """Authentication token."""
    token: str
    token_type: str  # bearer, api_key, jwt
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class CredentialManager:
    """
    Secure credential storage using Fernet encryption.
    """

    def __init__(self, storage_path: Path, master_key: bytes = None):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate or load master key
        key_path = storage_path.with_suffix(".key")
        if master_key:
            self._master_key = master_key
        elif key_path.exists():
            self._master_key = key_path.read_bytes()
        else:
            self._master_key = Fernet.generate_key()
            key_path.write_bytes(self._master_key)
            # Restrict permissions (Windows)
            try:
                import stat
                key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass

        self._fernet = Fernet(self._master_key)
        self._credentials: Dict[str, Credential] = {}
        self._load()

    def _load(self) -> None:
        """Load credentials from storage."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for cred_data in data.get("credentials", []):
                    cred = Credential(**cred_data)
                    self._credentials[cred.id] = cred
                logger.info(f"Loaded {len(self._credentials)} credentials")
            except Exception as e:
                logger.error(f"Failed to load credentials: {e}")

    def _save(self) -> None:
        """Save credentials to storage."""
        try:
            data = {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "credentials": []
            }
            for cred in self._credentials.values():
                cred_dict = {
                    "id": cred.id,
                    "name": cred.name,
                    "type": cred.type,
                    "value": cred.value,  # Already encrypted
                    "metadata": cred.metadata,
                    "created_at": cred.created_at.isoformat(),
                    "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                    "last_used": cred.last_used.isoformat() if cred.last_used else None,
                    "tags": cred.tags
                }
                data["credentials"].append(cred_dict)

            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")

    def _encrypt(self, value: str) -> str:
        """Encrypt a value."""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, encrypted_value: str) -> str:
        """Decrypt a value."""
        return self._fernet.decrypt(encrypted_value.encode()).decode()

    def store(
        self,
        name: str,
        value: str,
        cred_type: str = "api_key",
        metadata: Dict = None,
        expires_at: datetime = None,
        tags: List[str] = None
    ) -> Credential:
        """Store a credential."""
        cred = Credential(
            id=secrets.token_hex(8),
            name=name,
            type=cred_type,
            value=self._encrypt(value),
            metadata=metadata or {},
            expires_at=expires_at,
            tags=tags or []
        )
        self._credentials[cred.id] = cred
        self._save()
        logger.info(f"Stored credential: {name} ({cred.id})")
        return cred

    def get(self, credential_id: str) -> Optional[str]:
        """Get decrypted credential value."""
        cred = self._credentials.get(credential_id)
        if not cred:
            return None

        if cred.expires_at and cred.expires_at < datetime.now():
            logger.warning(f"Credential expired: {cred.name}")
            return None

        cred.last_used = datetime.now()
        self._save()
        return self._decrypt(cred.value)

    def get_by_name(self, name: str) -> Optional[str]:
        """Get credential by name."""
        for cred in self._credentials.values():
            if cred.name == name:
                return self.get(cred.id)
        return None

    def list_credentials(self, cred_type: str = None, tags: List[str] = None) -> List[Credential]:
        """List credentials (without values)."""
        creds = list(self._credentials.values())
        if cred_type:
            creds = [c for c in creds if c.type == cred_type]
        if tags:
            creds = [c for c in creds if any(t in c.tags for t in tags)]
        return creds

    def delete(self, credential_id: str) -> bool:
        """Delete a credential."""
        if credential_id in self._credentials:
            del self._credentials[credential_id]
            self._save()
            return True
        return False

    def update_metadata(self, credential_id: str, metadata: Dict) -> bool:
        """Update credential metadata."""
        cred = self._credentials.get(credential_id)
        if cred:
            cred.metadata.update(metadata)
            self._save()
            return True
        return False


class JWTManager:
    """
    JWT token management for service-to-service auth.
    """

    def __init__(self, secret_key: str = None, algorithm: str = "HS256"):
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.algorithm = algorithm

    def create_token(
        self,
        subject: str,
        scopes: List[str] = None,
        expires_in: int = 3600,  # seconds
        extra_claims: Dict = None
    ) -> str:
        """Create a JWT token."""
        now = datetime.utcnow()
        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "scopes": scopes or [],
            "jti": secrets.token_hex(8)
        }
        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
        return None

    def refresh_token(self, token: str, expires_in: int = 3600) -> Optional[str]:
        """Refresh a valid token."""
        payload = self.verify_token(token)
        if not payload:
            return None

        # Remove exp and iat, create new
        payload.pop("exp", None)
        payload.pop("iat", None)
        return self.create_token(
            subject=payload["sub"],
            scopes=payload.get("scopes", []),
            expires_in=expires_in
        )


class APIKeyManager:
    """
    API Key generation and validation.
    """

    def __init__(self, credential_manager: CredentialManager = None):
        self.credential_manager = credential_manager
        self._keys: Dict[str, Dict] = {}  # key_hash -> key_info

    def generate_key(
        self,
        name: str,
        scopes: List[str] = None,
        expires_in_days: int = 365,
        rate_limit: int = 1000  # per hour
    ) -> tuple[str, str]:
        """Generate a new API key. Returns (key_id, key_secret)."""
        key_id = "jk_" + secrets.token_urlsafe(16)
        key_secret = secrets.token_urlsafe(32)

        # Store hash
        key_hash = hashlib.sha256(key_secret.encode()).hexdigest()
        self._keys[key_hash] = {
            "key_id": key_id,
            "name": name,
            "scopes": scopes or [],
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=expires_in_days)).isoformat(),
            "rate_limit": rate_limit,
            "last_used": None,
            "call_count": 0
        }

        # Also store in credential manager if available
        if self.credential_manager:
            self.credential_manager.store(
                name=f"api_key_{key_id}",
                value=key_secret,
                cred_type="api_key",
                metadata={"key_id": key_id, "scopes": scopes or []},
                tags=["api_key"]
            )

        return key_id, key_secret

    def validate_key(self, key_secret: str) -> Optional[Dict]:
        """Validate an API key and return key info."""
        key_hash = hashlib.sha256(key_secret.encode()).hexdigest()
        key_info = self._keys.get(key_hash)

        if not key_info:
            return None

        # Check expiration
        if key_info.get("expires_at"):
            if datetime.fromisoformat(key_info["expires_at"]) < datetime.now():
                return None

        # Update usage
        key_info["last_used"] = datetime.now().isoformat()
        key_info["call_count"] += 1

        return key_info

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key by ID."""
        for key_hash, info in list(self._keys.items()):
            if info["key_id"] == key_id:
                del self._keys[key_hash]
                return True
        return False

    def list_keys(self) -> List[Dict]:
        """List all API keys (without secrets)."""
        return [
            {k: v for k, v in info.items() if k != "key_secret"}
            for info in self._keys.values()
        ]


class SessionManager:
    """
    User session management with secure tokens.
    """

    def __init__(self, secret_key: str = None, default_ttl: int = 86400):  # 24 hours
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.default_ttl = default_ttl
        self._sessions: Dict[str, Dict] = {}  # session_id -> session_data

    def create_session(
        self,
        user_id: str,
        metadata: Dict = None,
        ttl: int = None
    ) -> str:
        """Create a new session."""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=ttl or self.default_ttl)

        self._sessions[session_id] = {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "metadata": metadata or {},
            "last_activity": datetime.now().isoformat()
        }

        return session_id

    def validate_session(self, session_id: str) -> Optional[Dict]:
        """Validate and get session data."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        if datetime.fromisoformat(session["expires_at"]) < datetime.now():
            del self._sessions[session_id]
            return None

        # Update last activity
        session["last_activity"] = datetime.now().isoformat()
        return session

    def extend_session(self, session_id: str, ttl: int = None) -> bool:
        """Extend session TTL."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session["expires_at"] = (datetime.now() + timedelta(seconds=ttl or self.default_ttl)).isoformat()
        return True

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def revoke_user_sessions(self, user_id: str) -> int:
        """Revoke all sessions for a user."""
        count = 0
        for sid, session in list(self._sessions.items()):
            if session["user_id"] == user_id:
                del self._sessions[sid]
                count += 1
        return count


# Global instances
_credential_manager: Optional[CredentialManager] = None
_jwt_manager: Optional[JWTManager] = None
_api_key_manager: Optional[APIKeyManager] = None
_session_manager: Optional[SessionManager] = None


def get_credential_manager(storage_path: Path = None) -> CredentialManager:
    """Get or create global CredentialManager."""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager(storage_path or Path("security/credentials.json"))
    return _credential_manager


def get_jwt_manager(secret_key: str = None) -> JWTManager:
    """Get or create global JWTManager."""
    global _jwt_manager
    if _jwt_manager is None:
        _jwt_manager = JWTManager(secret_key)
    return _jwt_manager


def get_api_key_manager() -> APIKeyManager:
    """Get or create global APIKeyManager."""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager(get_credential_manager())
    return _api_key_manager


def get_session_manager() -> SessionManager:
    """Get or create global SessionManager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


# High-level async functions for tool integration
async def auth_store_credential(
    name: str,
    value: str,
    cred_type: str = "api_key",
    metadata: dict = None,
    expires_days: int = None,
    tags: list = None
) -> dict:
    """Store a credential securely."""
    manager = get_credential_manager()
    expires_at = datetime.now() + timedelta(days=expires_days) if expires_days else None
    cred = manager.store(name, value, cred_type, metadata, expires_at, tags)
    return {"success": True, "credential_id": cred.id, "name": cred.name}


async def auth_get_credential(credential_id: str = None, name: str = None) -> dict:
    """Retrieve a credential value."""
    manager = get_credential_manager()
    value = None
    if credential_id:
        value = manager.get(credential_id)
    elif name:
        value = manager.get_by_name(name)

    if value is None:
        return {"success": False, "error": "Credential not found or expired"}

    return {"success": True, "value": value}


async def auth_list_credentials(cred_type: str = None, tags: list = None) -> dict:
    """List stored credentials."""
    manager = get_credential_manager()
    creds = manager.list_credentials(cred_type, tags)
    return {
        "success": True,
        "credentials": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "metadata": c.metadata,
                "created_at": c.created_at.isoformat(),
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "last_used": c.last_used.isoformat() if c.last_used else None,
                "tags": c.tags
            }
            for c in creds
        ]
    }


async def auth_delete_credential(credential_id: str) -> dict:
    """Delete a credential."""
    manager = get_credential_manager()
    success = manager.delete(credential_id)
    return {"success": success}


async def auth_create_jwt(subject: str, scopes: list = None, expires_in: int = 3600, extra: dict = None) -> dict:
    """Create JWT token."""
    manager = get_jwt_manager()
    token = manager.create_token(subject, scopes, expires_in, extra)
    return {"success": True, "token": token, "expires_in": expires_in}


async def auth_verify_jwt(token: str) -> dict:
    """Verify JWT token."""
    manager = get_jwt_manager()
    payload = manager.verify_token(token)
    if payload:
        return {"success": True, "payload": payload}
    return {"success": False, "error": "Invalid or expired token"}


async def auth_generate_api_key(name: str, scopes: list = None, expires_days: int = 365, rate_limit: int = 1000) -> dict:
    """Generate API key."""
    manager = get_api_key_manager()
    key_id, key_secret = manager.generate_key(name, scopes, expires_days, rate_limit)
    return {"success": True, "key_id": key_id, "key_secret": key_secret}


async def auth_validate_api_key(key_secret: str) -> dict:
    """Validate API key."""
    manager = get_api_key_manager()
    info = manager.validate_key(key_secret)
    if info:
        return {"success": True, "key_info": info}
    return {"success": False, "error": "Invalid or expired API key"}


async def auth_create_session(user_id: str, metadata: dict = None, ttl: int = None) -> dict:
    """Create user session."""
    manager = get_session_manager()
    session_id = manager.create_session(user_id, metadata, ttl)
    return {"success": True, "session_id": session_id}


async def auth_validate_session(session_id: str) -> dict:
    """Validate session."""
    manager = get_session_manager()
    session = manager.validate_session(session_id)
    if session:
        return {"success": True, "session": session}
    return {"success": False, "error": "Invalid or expired session"}


async def auth_revoke_session(session_id: str) -> dict:
    """Revoke session."""
    manager = get_session_manager()
    success = manager.revoke_session(session_id)
    return {"success": success}