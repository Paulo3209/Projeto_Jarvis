"""
Android App Module - Flutter app communication bridge for JARVIS.
Provides WebSocket/API bridge for mobile app integration.
"""
from .bridge import AndroidBridge, AndroidConfig, get_android_bridge
from .notifications import NotificationManager, NotificationType, send_notification
from .commands import CommandHandler, CommandType, handle_mobile_command

__all__ = [
    "AndroidBridge",
    "AndroidConfig",
    "get_android_bridge",
    "NotificationManager",
    "NotificationType",
    "send_notification",
    "CommandHandler",
    "CommandType",
    "handle_mobile_command",
]