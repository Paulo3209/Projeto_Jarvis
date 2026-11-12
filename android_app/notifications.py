"""
Notifications Module - Push notification management for Android app.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Notification types."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    COMMAND_RESULT = "command_result"
    DEVICE_ALERT = "device_alert"
    SECURITY_ALERT = "security_alert"
    VOICE_TRANSCRIPTION = "voice_transcription"
    SYSTEM_STATUS = "system_status"


@dataclass
class Notification:
    """Notification data."""
    id: str
    title: str
    body: str
    notification_type: NotificationType
    timestamp: datetime
    data: Dict = None
    read: bool = False
    priority: int = 1  # 1=low, 2=normal, 3=high, 4=urgent

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "type": self.notification_type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data or {},
            "read": self.read,
            "priority": self.priority,
        }


class NotificationManager:
    """
    Manages notifications for mobile clients.
    Handles queuing, delivery, and persistence.
    """

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._notifications: List[Notification] = []
        self._pending: Dict[str, List[Notification]] = {}  # client_id -> notifications
        self._subscribers: Dict[str, asyncio.Queue] = {}

    def create_notification(
        self,
        title: str,
        body: str,
        notification_type: NotificationType = NotificationType.INFO,
        data: Dict = None,
        priority: int = 2,
    ) -> Notification:
        """Create a new notification."""
        import secrets
        notification = Notification(
            id=secrets.token_hex(8),
            title=title,
            body=body,
            notification_type=notification_type,
            timestamp=datetime.now(),
            data=data or {},
            priority=priority,
        )
        self._notifications.append(notification)
        # Trim history
        if len(self._notifications) > self.max_history:
            self._notifications = self._notifications[-self.max_history:]
        return notification

    async def send_to_client(self, client_id: str, notification: Notification) -> bool:
        """Queue notification for specific client."""
        if client_id not in self._pending:
            self._pending[client_id] = []
        self._pending[client_id].append(notification)

        # Notify subscriber if any
        if client_id in self._subscribers:
            try:
                self._subscribers[client_id].put_nowait(notification)
            except asyncio.QueueFull:
                pass

        return True

    async def broadcast(self, notification: Notification, client_ids: List[str] = None) -> int:
        """Broadcast notification to multiple clients."""
        targets = client_ids or list(self._pending.keys())
        sent = 0
        for client_id in targets:
            if await self.send_to_client(client_id, notification):
                sent += 1
        return sent

    def get_pending(self, client_id: str, limit: int = 50) -> List[Notification]:
        """Get pending notifications for client."""
        notifications = self._pending.get(client_id, [])
        return notifications[-limit:]

    def mark_read(self, client_id: str, notification_id: str) -> bool:
        """Mark notification as read."""
        for n in self._pending.get(client_id, []):
            if n.id == notification_id:
                n.read = True
                return True
        return False

    def clear_read(self, client_id: str) -> int:
        """Clear read notifications for client."""
        notifications = self._pending.get(client_id, [])
        original_len = len(notifications)
        self._pending[client_id] = [n for n in notifications if not n.read]
        return original_len - len(self._pending[client_id])

    def get_history(self, limit: int = 100, notification_type: NotificationType = None) -> List[Notification]:
        """Get notification history."""
        history = self._notifications
        if notification_type:
            history = [n for n in history if n.notification_type == notification_type]
        return history[-limit:]

    def subscribe(self, client_id: str) -> asyncio.Queue:
        """Subscribe to real-time notifications."""
        queue = asyncio.Queue(maxsize=100)
        self._subscribers[client_id] = queue
        return queue

    def unsubscribe(self, client_id: str) -> None:
        """Unsubscribe from notifications."""
        if client_id in self._subscribers:
            del self._subscribers[client_id]


# Global instance
_notification_manager: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """Get global notification manager."""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager


async def send_notification(
    title: str,
    body: str,
    notification_type: NotificationType = NotificationType.INFO,
    client_id: str = None,
    data: Dict = None,
    priority: int = 2,
) -> Dict:
    """Send notification via global manager."""
    manager = get_notification_manager()
    notification = manager.create_notification(title, body, notification_type, data, priority)

    if client_id:
        await manager.send_to_client(client_id, notification)
        return {"success": True, "notification": notification.to_dict()}
    else:
        sent = await manager.broadcast(notification)
        return {"success": True, "sent_to": sent, "notification": notification.to_dict()}