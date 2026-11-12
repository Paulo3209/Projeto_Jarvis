"""
Permissions Agent - Security and access control for JARVIS.
Manages user approvals, tool permissions, and operation auditing.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
    """Permission levels."""
    DENY = "deny"
    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    ALLOW_ALWAYS = "allow_always"


class RiskLevel(Enum):
    """Risk levels for operations."""
    LOW = "low"           # Read-only, safe operations
    MEDIUM = "medium"     # Modifications, non-destructive
    HIGH = "high"         # Destructive, system changes
    CRITICAL = "critical" # Security-sensitive, irreversible


@dataclass
class PermissionRule:
    """A permission rule for a tool/operation."""
    tool_pattern: str  # Glob pattern for tool name
    risk_level: RiskLevel
    requires_approval: bool = True
    allowed_users: List[str] = field(default_factory=list)  # Empty = all
    allowed_contexts: List[str] = field(default_factory=list)  # Empty = all
    max_calls_per_minute: int = 0  # 0 = unlimited
    max_calls_per_hour: int = 0
    description: str = ""


@dataclass
class ApprovalRequest:
    """A pending approval request."""
    id: str
    tool_name: str
    args: Dict
    risk_level: RiskLevel
    reason: str
    requested_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    decided: bool = False
    decision: Optional[PermissionLevel] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class AuditEntry:
    """Audit log entry."""
    id: str
    timestamp: datetime
    tool_name: str
    args: Dict
    result: Dict
    user: str = "local"
    session_id: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    approved: bool = False
    approval_id: Optional[str] = None


class PermissionManager:
    """
    Manages permissions, approvals, and audit logging.
    """

    def __init__(
        self,
        audit_path: Path = None,
        rules: List[PermissionRule] = None,
        approval_callback: Callable[[ApprovalRequest], PermissionLevel] = None
    ):
        self.audit_path = audit_path or Path("security/audit.log")
        self.rules = rules or self._default_rules()
        self.approval_callback = approval_callback
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
        self._approved_cache: Dict[str, PermissionLevel] = {}  # tool_hash -> level
        self._call_counts: Dict[str, List[float]] = {}  # tool_name -> timestamps
        self._session_id = secrets.token_hex(8)
        self._audit_buffer: List[AuditEntry] = []
        self._audit_flush_interval = 10  # seconds
        self._last_flush = time.time()

        # Start audit flusher
        self._flusher_task: Optional[asyncio.Task] = None

    def _default_rules(self) -> List[PermissionRule]:
        """Default permission rules."""
        return [
            # Safe read-only operations
            PermissionRule(
                tool_pattern="get_*",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                description="Read-only information gathering"
            ),
            PermissionRule(
                tool_pattern="list_*",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                description="Listing operations"
            ),
            PermissionRule(
                tool_pattern="recall_*",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                description="Memory recall"
            ),
            PermissionRule(
                tool_pattern="screen_*",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                description="Screen capture and OCR"
            ),
            PermissionRule(
                tool_pattern="camera_list",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            PermissionRule(
                tool_pattern="detector_get_classes",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),

            # File operations - medium risk
            PermissionRule(
                tool_pattern="read_file",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            PermissionRule(
                tool_pattern="write_file",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="File creation/modification"
            ),
            PermissionRule(
                tool_pattern="delete_file",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="File deletion"
            ),

            # System control - medium to high
            PermissionRule(
                tool_pattern="open_*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Opening applications"
            ),
            PermissionRule(
                tool_pattern="*hotkey*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Keyboard shortcuts"
            ),
            PermissionRule(
                tool_pattern="*click*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Mouse clicks"
            ),
            PermissionRule(
                tool_pattern="*type*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Text input"
            ),

            # Device control - high risk
            PermissionRule(
                tool_pattern="*device*",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="Device management"
            ),
            PermissionRule(
                tool_pattern="*adb*",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="Android control"
            ),
            PermissionRule(
                tool_pattern="*ble*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Bluetooth operations"
            ),

            # Smart home - medium
            PermissionRule(
                tool_pattern="hass_*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Home Assistant control"
            ),

            # Network - medium to high
            PermissionRule(
                tool_pattern="network_*",
                risk_level=RiskLevel.MEDIUM,
                requires_approval=True,
                description="Network operations"
            ),
            PermissionRule(
                tool_pattern="ssh_*",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="SSH operations"
            ),

            # Dangerous operations
            PermissionRule(
                tool_pattern="*reboot*",
                risk_level=RiskLevel.CRITICAL,
                requires_approval=True,
                description="System reboot"
            ),
            PermissionRule(
                tool_pattern="*uninstall*",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="Uninstalling apps"
            ),
            PermissionRule(
                tool_pattern="*install*",
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                description="Installing software"
            ),
        ]

    def get_rule(self, tool_name: str) -> Optional[PermissionRule]:
        """Get matching rule for tool."""
        import fnmatch
        for rule in self.rules:
            if fnmatch.fnmatch(tool_name, rule.tool_pattern):
                return rule
        # Default: medium risk, requires approval
        return PermissionRule(
            tool_pattern="*",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True
        )

    def check_rate_limit(self, tool_name: str, rule: PermissionRule) -> bool:
        """Check if tool call is within rate limits."""
        now = time.time()

        if tool_name not in self._call_counts:
            self._call_counts[tool_name] = []

        # Clean old timestamps
        self._call_counts[tool_name] = [
            t for t in self._call_counts[tool_name]
            if now - t < 3600  # Keep last hour
        ]

        # Check per-minute limit
        if rule.max_calls_per_minute > 0:
            recent_minute = sum(1 for t in self._call_counts[tool_name] if now - t < 60)
            if recent_minute >= rule.max_calls_per_minute:
                return False

        # Check per-hour limit
        if rule.max_calls_per_hour > 0:
            recent_hour = len(self._call_counts[tool_name])
            if recent_hour >= rule.max_calls_per_hour:
                return False

        return True

    def record_call(self, tool_name: str) -> None:
        """Record a tool call for rate limiting."""
        if tool_name not in self._call_counts:
            self._call_counts[tool_name] = []
        self._call_counts[tool_name].append(time.time())

    async def check_permission(
        self,
        tool_name: str,
        args: Dict,
        user: str = "local",
        context: str = ""
    ) -> tuple[bool, Optional[ApprovalRequest]]:
        """
        Check if tool execution is permitted.
        Returns (allowed, approval_request_if_pending).
        """
        rule = self.get_rule(tool_name)

        # Check user allowance
        if rule.allowed_users and user not in rule.allowed_users:
            return False, None

        # Check context allowance
        if rule.allowed_contexts and context not in rule.allowed_contexts:
            return False, None

        # Check rate limit
        if not self.check_rate_limit(tool_name, rule):
            return False, None

        # Check cache for ALLOW_ALWAYS
        tool_hash = self._hash_tool_call(tool_name, args)
        if tool_hash in self._approved_cache:
            cached_level = self._approved_cache[tool_hash]
            if cached_level == PermissionLevel.ALLOW_ALWAYS:
                return True, None
            elif cached_level == PermissionLevel.ALLOW_SESSION:
                return True, None

        # Low risk, no approval required
        if not rule.requires_approval or rule.risk_level == RiskLevel.LOW:
            return True, None

        # Check for ALLOW_ONCE in cache
        if tool_hash in self._approved_cache:
            if self._approved_cache[tool_hash] == PermissionLevel.ALLOW_ONCE:
                # Consume the allowance
                del self._approved_cache[tool_hash]
                return True, None

        # Need approval
        approval = ApprovalRequest(
            id=secrets.token_hex(8),
            tool_name=tool_name,
            args=args,
            risk_level=rule.risk_level,
            reason=f"{rule.description}: {tool_name}",
            expires_at=datetime.now() + timedelta(minutes=5)
        )

        self._pending_approvals[approval.id] = approval

        # Try to get approval via callback
        if self.approval_callback:
            try:
                decision = self.approval_callback(approval)
                return await self._process_approval(approval.id, decision)
            except Exception as e:
                logger.error(f"Approval callback error: {e}")

        return False, approval

    async def _process_approval(
        self,
        approval_id: str,
        decision: PermissionLevel
    ) -> tuple[bool, Optional[ApprovalRequest]]:
        """Process an approval decision."""
        approval = self._pending_approvals.get(approval_id)
        if not approval:
            return False, None

        approval.decided = True
        approval.decision = decision
        approval.decided_at = datetime.now()

        if decision in (PermissionLevel.ALLOW_ONCE, PermissionLevel.ALLOW_SESSION, PermissionLevel.ALLOW_ALWAYS):
            tool_hash = self._hash_tool_call(approval.tool_name, approval.args)
            self._approved_cache[tool_hash] = decision
            del self._pending_approvals[approval_id]
            return True, approval
        else:
            del self._pending_approvals[approval_id]
            return False, approval

    async def respond_to_approval(self, approval_id: str, decision: PermissionLevel) -> bool:
        """Respond to a pending approval request."""
        allowed, _ = await self._process_approval(approval_id, decision)
        return allowed

    def get_pending_approvals(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        # Clean expired
        now = datetime.now()
        expired = [aid for aid, a in self._pending_approvals.items() if a.expires_at and a.expires_at < now]
        for aid in expired:
            del self._pending_approvals[aid]

        return list(self._pending_approvals.values())

    def _hash_tool_call(self, tool_name: str, args: Dict) -> str:
        """Create hash for tool call caching."""
        content = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def log_audit(
        self,
        tool_name: str,
        args: Dict,
        result: Dict,
        user: str = "local",
        risk_level: RiskLevel = RiskLevel.LOW,
        approved: bool = False,
        approval_id: str = None
    ) -> None:
        """Log an audit entry."""
        entry = AuditEntry(
            id=secrets.token_hex(8),
            timestamp=datetime.now(),
            tool_name=tool_name,
            args=args,
            result=result,
            user=user,
            session_id=self._session_id,
            risk_level=risk_level,
            approved=approved,
            approval_id=approval_id
        )
        self._audit_buffer.append(entry)

        # Flush periodically
        if time.time() - self._last_flush > self._audit_flush_interval:
            self._flush_audit()

    def _flush_audit(self) -> None:
        """Flush audit buffer to disk."""
        if not self._audit_buffer:
            return

        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                for entry in self._audit_buffer:
                    f.write(json.dumps({
                        "id": entry.id,
                        "timestamp": entry.timestamp.isoformat(),
                        "tool_name": entry.tool_name,
                        "args": entry.args,
                        "result": entry.result,
                        "user": entry.user,
                        "session_id": entry.session_id,
                        "risk_level": entry.risk_level.value,
                        "approved": entry.approved,
                        "approval_id": entry.approval_id
                    }, ensure_ascii=False) + "\n")
            self._audit_buffer.clear()
            self._last_flush = time.time()
        except Exception as e:
            logger.error(f"Audit flush error: {e}")

    def get_audit_log(
        self,
        limit: int = 100,
        tool_name: str = None,
        risk_level: RiskLevel = None,
        since: datetime = None
    ) -> List[Dict]:
        """Get recent audit log entries."""
        entries = []

        # Read from file
        if self.audit_path.exists():
            try:
                with open(self.audit_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            # Apply filters
                            if tool_name and entry.get("tool_name") != tool_name:
                                continue
                            if risk_level and entry.get("risk_level") != risk_level.value:
                                continue
                            if since:
                                entry_time = datetime.fromisoformat(entry["timestamp"])
                                if entry_time < since:
                                    continue
                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"Audit read error: {e}")

        # Add buffer entries
        for entry in self._audit_buffer:
            if tool_name and entry.tool_name != tool_name:
                continue
            if risk_level and entry.risk_level != risk_level:
                continue
            if since and entry.timestamp < since:
                continue
            entries.append({
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "tool_name": entry.tool_name,
                "args": entry.args,
                "result": entry.result,
                "user": entry.user,
                "session_id": entry.session_id,
                "risk_level": entry.risk_level.value,
                "approved": entry.approved,
                "approval_id": entry.approval_id
            })

        # Sort by timestamp descending
        entries.sort(key=lambda e: e["timestamp"], reverse=True)
        return entries[:limit]

    def add_rule(self, rule: PermissionRule) -> None:
        """Add a custom permission rule."""
        self.rules.insert(0, rule)  # Higher priority

    def remove_rule(self, tool_pattern: str) -> bool:
        """Remove a rule by pattern."""
        for i, rule in enumerate(self.rules):
            if rule.tool_pattern == tool_pattern:
                self.rules.pop(i)
                return True
        return False

    def get_rules(self) -> List[Dict]:
        """Get all permission rules."""
        return [
            {
                "tool_pattern": r.tool_pattern,
                "risk_level": r.risk_level.value,
                "requires_approval": r.requires_approval,
                "allowed_users": r.allowed_users,
                "allowed_contexts": r.allowed_contexts,
                "max_calls_per_minute": r.max_calls_per_minute,
                "max_calls_per_hour": r.max_calls_per_hour,
                "description": r.description
            }
            for r in self.rules
        ]


# Global instance
_permission_manager: Optional[PermissionManager] = None


def get_permission_manager(
    audit_path: Path = None,
    approval_callback: Callable = None
) -> PermissionManager:
    """Get or create global PermissionManager instance."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager(audit_path, approval_callback=approval_callback)
    return _permission_manager


# High-level async functions for tool integration
async def permissions_check(tool_name: str, args: dict, user: str = "local", context: str = "") -> dict:
    """Check if tool execution is permitted."""
    manager = get_permission_manager()
    allowed, approval = await manager.check_permission(tool_name, args, user, context)
    return {
        "success": True,
        "allowed": allowed,
        "approval_required": approval is not None,
        "approval_id": approval.id if approval else None,
        "risk_level": approval.risk_level.value if approval else "low"
    }


async def permissions_respond(approval_id: str, decision: str) -> dict:
    """Respond to an approval request."""
    manager = get_permission_manager()
    try:
        level = PermissionLevel(decision)
    except ValueError:
        return {"success": False, "error": f"Invalid decision: {decision}"}

    allowed = await manager.respond_to_approval(approval_id, level)
    return {"success": True, "allowed": allowed}


async def permissions_pending() -> dict:
    """Get pending approval requests."""
    manager = get_permission_manager()
    approvals = manager.get_pending_approvals()
    return {
        "success": True,
        "approvals": [
            {
                "id": a.id,
                "tool_name": a.tool_name,
                "args": a.args,
                "risk_level": a.risk_level.value,
                "reason": a.reason,
                "requested_at": a.requested_at.isoformat(),
                "expires_at": a.expires_at.isoformat() if a.expires_at else None
            }
            for a in approvals
        ]
    }


async def permissions_audit(
    limit: int = 100,
    tool_name: str = None,
    risk_level: str = None,
    hours: int = 24
) -> dict:
    """Get audit log."""
    manager = get_permission_manager()
    since = datetime.now() - timedelta(hours=hours) if hours else None
    rl = RiskLevel(risk_level) if risk_level else None
    entries = manager.get_audit_log(limit=limit, tool_name=tool_name, risk_level=rl, since=since)
    return {"success": True, "entries": entries}


async def permissions_rules() -> dict:
    """List permission rules."""
    manager = get_permission_manager()
    return {"success": True, "rules": manager.get_rules()}


async def permissions_add_rule(
    tool_pattern: str,
    risk_level: str,
    requires_approval: bool = True,
    description: str = ""
) -> dict:
    """Add a permission rule."""
    manager = get_permission_manager()
    try:
        rl = RiskLevel(risk_level)
    except ValueError:
        return {"success": False, "error": f"Invalid risk level: {risk_level}"}

    rule = PermissionRule(
        tool_pattern=tool_pattern,
        risk_level=rl,
        requires_approval=requires_approval,
        description=description
    )
    manager.add_rule(rule)
    return {"success": True, "rule": tool_pattern}