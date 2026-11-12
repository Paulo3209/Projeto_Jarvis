"""
Security Audit Module - Comprehensive audit logging for JARVIS.
Tracks all security-relevant events with tamper-evident logging.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from queue import Queue, Empty

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    # Authentication
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    TOKEN_CREATED = "token_created"
    TOKEN_REVOKED = "token_revoked"
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"

    # Authorization
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_CHANGED = "permission_changed"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"

    # Device Management
    DEVICE_REGISTERED = "device_registered"
    DEVICE_CONNECTED = "device_connected"
    DEVICE_DISCONNECTED = "device_disconnected"
    DEVICE_BLOCKED = "device_blocked"
    DEVICE_UNBLOCKED = "device_unblocked"
    DEVICE_TRUST_CHANGED = "device_trust_changed"
    DEVICE_COMMAND = "device_command"

    # Tool Execution
    TOOL_EXECUTED = "tool_executed"
    TOOL_FAILED = "tool_failed"
    TOOL_APPROVED = "tool_approved"
    TOOL_DENIED = "tool_denied"

    # Data Access
    DATA_READ = "data_read"
    DATA_WRITTEN = "data_written"
    DATA_DELETED = "data_deleted"
    CREDENTIAL_ACCESSED = "credential_accessed"
    CREDENTIAL_CREATED = "credential_created"
    CREDENTIAL_DELETED = "credential_deleted"

    # System
    CONFIG_CHANGED = "config_changed"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"

    # Security
    SECURITY_VIOLATION = "security_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    ENCRYPTION_KEY_ROTATED = "encryption_key_rotated"


class AuditSeverity(Enum):
    """Audit event severity."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Immutable audit event."""
    id: str
    timestamp: datetime
    event_type: AuditEventType
    severity: AuditSeverity
    user: str
    session_id: str
    source: str  # tool, component, IP
    action: str
    result: str  # success, failure, partial
    details: Dict = field(default_factory=dict)
    risk_score: int = 0  # 0-100
    tags: List[str] = field(default_factory=list)
    previous_hash: str = ""  # For tamper-evident chaining
    hash: str = ""  # This event's hash

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "user": self.user,
            "session_id": self.session_id,
            "source": self.source,
            "action": self.action,
            "result": self.result,
            "details": self.details,
            "risk_score": self.risk_score,
            "tags": self.tags,
            "previous_hash": self.previous_hash,
            "hash": self.hash
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'AuditEvent':
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            event_type=AuditEventType(data["event_type"]),
            severity=AuditSeverity(data["severity"]),
            user=data["user"],
            session_id=data["session_id"],
            source=data["source"],
            action=data["action"],
            result=data["result"],
            details=data.get("details", {}),
            risk_score=data.get("risk_score", 0),
            tags=data.get("tags", []),
            previous_hash=data.get("previous_hash", ""),
            hash=data.get("hash", "")
        )


class TamperEvidentLog:
    """
    Tamper-evident audit log using hash chaining.
    Each event includes hash of previous event.
    """

    def __init__(self, log_path: Path, secret_key: bytes = None):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Secret key for HMAC
        key_path = log_path.with_suffix(".hmac")
        if secret_key:
            self._secret_key = secret_key
        elif key_path.exists():
            self._secret_key = key_path.read_bytes()
        else:
            self._secret_key = secrets.token_bytes(32)
            key_path.write_bytes(self._secret_key)

        self._last_hash = ""
        self._event_count = 0
        self._verify_chain()

    def _compute_hash(self, event: AuditEvent) -> str:
        """Compute HMAC-SHA256 hash of event."""
        # Create canonical representation
        canonical = f"{event.id}|{event.timestamp.isoformat()}|{event.event_type.value}|{event.user}|{event.action}|{event.result}|{json.dumps(event.details, sort_keys=True)}|{event.previous_hash}"
        hmac_hash = hmac.new(self._secret_key, canonical.encode(), hashlib.sha256).hexdigest()
        return hmac_hash

    def _verify_chain(self) -> bool:
        """Verify hash chain integrity on startup."""
        if not self.log_path.exists():
            self._last_hash = ""
            self._event_count = 0
            return True

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                last_hash = ""
                count = 0
                for line in f:
                    try:
                        event = AuditEvent.from_dict(json.loads(line))
                        expected_hash = self._compute_hash(event)
                        if event.hash != expected_hash:
                            logger.critical(f"AUDIT CHAIN BROKEN at event {event.id}: hash mismatch")
                            return False
                        if event.previous_hash != last_hash:
                            logger.critical(f"AUDIT CHAIN BROKEN at event {event.id}: previous_hash mismatch")
                            return False
                        last_hash = event.hash
                        count += 1
                    except Exception as e:
                        logger.error(f"Error verifying audit event: {e}")
                        return False

                self._last_hash = last_hash
                self._event_count = count
                logger.info(f"Audit chain verified: {count} events")
                return True
        except Exception as e:
            logger.error(f"Failed to verify audit chain: {e}")
            return False

    def append(self, event: AuditEvent) -> bool:
        """Append event to log with hash chaining."""
        event.previous_hash = self._last_hash
        event.hash = self._compute_hash(event)

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

            self._last_hash = event.hash
            self._event_count += 1
            return True
        except Exception as e:
            logger.error(f"Failed to write audit event: {e}")
            return False


class AuditLogger:
    """
    High-level audit logger with async writing and buffering.
    """

    def __init__(
        self,
        log_path: Path = None,
        secret_key: bytes = None,
        buffer_size: int = 100,
        flush_interval: float = 5.0
    ):
        self.log_path = log_path or Path("security/audit_tamper.log")
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval

        self._tamper_log = TamperEvidentLog(self.log_path, secret_key)
        self._buffer: Queue = Queue(maxsize=buffer_size * 2)
        self._flush_task: Optional[threading.Thread] = None
        self._running = False
        self._session_id = secrets.token_hex(8)

        # Risk scoring rules
        self._risk_rules = {
            AuditEventType.LOGIN_FAILURE: 30,
            AuditEventType.PERMISSION_DENIED: 20,
            AuditEventType.DEVICE_BLOCKED: 40,
            AuditEventType.SECURITY_VIOLATION: 80,
            AuditEventType.RATE_LIMIT_EXCEEDED: 50,
            AuditEventType.SUSPICIOUS_ACTIVITY: 70,
            AuditEventType.CREDENTIAL_ACCESSED: 10,
            AuditEventType.CREDENTIAL_CREATED: 15,
            AuditEventType.TOOL_DENIED: 25,
        }

        self._start_flusher()

    def _start_flusher(self) -> None:
        """Start background flush thread."""
        self._running = True
        self._flush_task = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_task.start()

    def _flush_loop(self) -> None:
        """Background flush loop."""
        last_flush = time.time()
        while self._running:
            try:
                # Flush if buffer full or interval elapsed
                if self._buffer.qsize() >= self.buffer_size or time.time() - last_flush > self.flush_interval:
                    self._flush_buffer()
                    last_flush = time.time()
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Audit flusher error: {e}")

    def _flush_buffer(self) -> None:
        """Flush buffered events to disk."""
        flushed = 0
        while not self._buffer.empty() and flushed < self.buffer_size:
            try:
                event = self._buffer.get_nowait()
                self._tamper_log.append(event)
                flushed += 1
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error flushing audit event: {e}")

    def log(
        self,
        event_type: AuditEventType,
        user: str,
        source: str,
        action: str,
        result: str,
        details: Dict = None,
        severity: AuditSeverity = None,
        tags: List[str] = None,
        session_id: str = None
    ) -> AuditEvent:
        """Log an audit event."""
        # Determine severity from result if not specified
        if severity is None:
            if result == "failure":
                severity = AuditSeverity.ERROR
            elif result == "partial":
                severity = AuditSeverity.WARNING
            else:
                severity = AuditSeverity.INFO

        # Calculate risk score
        risk_score = self._risk_rules.get(event_type, 0)
        if result == "failure":
            risk_score += 20
        elif result == "partial":
            risk_score += 10

        event = AuditEvent(
            id=secrets.token_hex(8),
            timestamp=datetime.now(),
            event_type=event_type,
            severity=severity,
            user=user,
            session_id=session_id or self._session_id,
            source=source,
            action=action,
            result=result,
            details=details or {},
            risk_score=min(risk_score, 100),
            tags=tags or []
        )

        # Add to buffer
        try:
            self._buffer.put_nowait(event)
        except Exception:
            # Buffer full, flush synchronously
            self._flush_buffer()
            try:
                self._buffer.put_nowait(event)
            except Exception:
                logger.error("Audit buffer full, dropping event")

        return event

    def log_tool_execution(
        self,
        tool_name: str,
        args: Dict,
        result: Dict,
        user: str = "local",
        session_id: str = None
    ) -> None:
        """Log tool execution."""
        success = result.get("success", False) if isinstance(result, dict) else False
        self.log(
            event_type=AuditEventType.TOOL_EXECUTED if success else AuditEventType.TOOL_FAILED,
            user=user,
            source=tool_name,
            action="execute",
            result="success" if success else "failure",
            details={
                "tool": tool_name,
                "args": args,
                "error": result.get("error") if isinstance(result, dict) else str(result)
            },
            session_id=session_id
        )

    def log_device_command(
        self,
        device_id: str,
        command: str,
        params: Dict,
        result: Dict,
        user: str = "local"
    ) -> None:
        """Log device command."""
        success = result.get("success", False) if isinstance(result, dict) else False
        self.log(
            event_type=AuditEventType.DEVICE_COMMAND,
            user=user,
            source=f"device:{device_id}",
            action=command,
            result="success" if success else "failure",
            details={
                "device_id": device_id,
                "command": command,
                "params": params,
                "error": result.get("error") if isinstance(result, dict) else str(result)
            }
        )

    def log_permission_check(
        self,
        tool_name: str,
        allowed: bool,
        risk_level: str,
        user: str = "local"
    ) -> None:
        """Log permission check."""
        self.log(
            event_type=AuditEventType.PERMISSION_GRANTED if allowed else AuditEventType.PERMISSION_DENIED,
            user=user,
            source=tool_name,
            action="permission_check",
            result="success" if allowed else "failure",
            details={
                "tool": tool_name,
                "risk_level": risk_level
            },
            severity=AuditSeverity.WARNING if not allowed else AuditSeverity.INFO
        )

    def get_recent_events(
        self,
        limit: int = 100,
        event_type: AuditEventType = None,
        severity: AuditSeverity = None,
        user: str = None,
        since: datetime = None
    ) -> List[AuditEvent]:
        """Get recent audit events."""
        events = []

        if not self.log_path.exists():
            return events

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = AuditEvent.from_dict(json.loads(line))

                        # Apply filters
                        if event_type and event.event_type != event_type:
                            continue
                        if severity and event.severity != severity:
                            continue
                        if user and event.user != user:
                            continue
                        if since and event.timestamp < since:
                            continue

                        events.append(event)
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"Error reading audit log: {e}")

        # Sort by timestamp descending
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def verify_integrity(self) -> Dict:
        """Verify audit log integrity."""
        return {
            "valid": self._tamper_log._verify_chain(),
            "event_count": self._tamper_log._event_count,
            "last_hash": self._tamper_log._last_hash
        }

    def shutdown(self) -> None:
        """Shutdown logger and flush remaining events."""
        self._running = False
        if self._flush_task:
            self._flush_task.join(timeout=5.0)
        self._flush_buffer()


# Global instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(log_path: Path = None, secret_key: bytes = None) -> AuditLogger:
    """Get or create global AuditLogger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(log_path, secret_key)
    return _audit_logger


# High-level async functions for tool integration
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
    """Log an audit event."""
    logger = get_audit_logger()
    try:
        etype = AuditEventType(event_type)
    except ValueError:
        return {"success": False, "error": f"Invalid event type: {event_type}"}

    sev = AuditSeverity(severity) if severity else None
    event = logger.log(etype, user, source, action, result, details, sev, tags, session_id)
    return {"success": True, "event_id": event.id}


async def audit_query(
    limit: int = 100,
    event_type: str = None,
    severity: str = None,
    user: str = None,
    hours: int = 24
) -> dict:
    """Query audit log."""
    logger = get_audit_logger()
    since = datetime.now() - timedelta(hours=hours) if hours else None
    etype = AuditEventType(event_type) if event_type else None
    sev = AuditSeverity(severity) if severity else None

    events = logger.get_recent_events(limit, etype, sev, user, since)
    return {
        "success": True,
        "events": [e.to_dict() for e in events]
    }


async def audit_verify() -> dict:
    """Verify audit log integrity."""
    logger = get_audit_logger()
    result = logger.verify_integrity()
    return {"success": True, "integrity": result}


async def audit_stats(hours: int = 24) -> dict:
    """Get audit statistics."""
    logger = get_audit_logger()
    since = datetime.now() - timedelta(hours=hours)
    events = logger.get_recent_events(limit=10000, since=since)

    stats = {
        "total_events": len(events),
        "by_type": {},
        "by_severity": {},
        "by_result": {},
        "by_user": {},
        "high_risk_events": 0
    }

    for event in events:
        stats["by_type"][event.event_type.value] = stats["by_type"].get(event.event_type.value, 0) + 1
        stats["by_severity"][event.severity.value] = stats["by_severity"].get(event.severity.value, 0) + 1
        stats["by_result"][event.result] = stats["by_result"].get(event.result, 0) + 1
        stats["by_user"][event.user] = stats["by_user"].get(event.user, 0) + 1
        if event.risk_score >= 50:
            stats["high_risk_events"] += 1

    return {"success": True, "stats": stats}