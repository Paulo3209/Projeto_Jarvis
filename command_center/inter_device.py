"""
Inter-Device Communication - Message routing and synchronization between devices.
Enables continuous communication and coordination across the device network.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.event_bus import EventBus, EventType, get_event_bus
from device_network.manager import get_device_network, DeviceNetworkManager, DeviceRole, DeviceStatus

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Inter-device message types."""
    COMMAND = "command"
    RESPONSE = "response"
    EVENT = "event"
    SYNC = "sync"
    HEARTBEAT = "heartbeat"
    STATE_UPDATE = "state_update"
    FILE_TRANSFER = "file_transfer"
    STREAM = "stream"
    BROADCAST = "broadcast"
    QUERY = "query"


class MessagePriority(Enum):
    """Message priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class InterDeviceMessage:
    """Message between devices."""
    message_id: str
    message_type: MessageType
    source_id: str
    target_id: str  # "broadcast" for broadcast
    payload: Dict
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    ttl: int = 5  # Max hops
    requires_ack: bool = False
    correlation_id: Optional[str] = None  # For request-response
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "message_id": self.message_id,
            "type": self.message_type.value,
            "source": self.source_id,
            "target": self.target_id,
            "payload": self.payload,
            "priority": self.priority.value,
            "timestamp": self.timestamp.isoformat(),
            "ttl": self.ttl,
            "requires_ack": self.requires_ack,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'InterDeviceMessage':
        return cls(
            message_id=data["message_id"],
            message_type=MessageType(data["type"]),
            source_id=data["source"],
            target_id=data["target"],
            payload=data["payload"],
            priority=MessagePriority(data.get("priority", 1)),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            ttl=data.get("ttl", 5),
            requires_ack=data.get("requires_ack", False),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Subscription:
    """Event subscription."""
    subscription_id: str
    subscriber_id: str
    event_types: List[str]
    filter: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class MessageRouter:
    """
    Routes messages between devices.
    Handles delivery, acknowledgments, and routing.
    """

    def __init__(self, network_manager: DeviceNetworkManager):
        self._network = network_manager
        self._pending_acks: Dict[str, asyncio.Future] = {}
        self._subscriptions: Dict[str, List[Subscription]] = {}  # event_type -> subscriptions
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default message handlers."""
        self._message_handlers = {
            MessageType.COMMAND: self._handle_command,
            MessageType.RESPONSE: self._handle_response,
            MessageType.EVENT: self._handle_event,
            MessageType.SYNC: self._handle_sync,
            MessageType.HEARTBEAT: self._handle_heartbeat,
            MessageType.STATE_UPDATE: self._handle_state_update,
        }

    def register_handler(self, msg_type: MessageType, handler: Callable) -> None:
        """Register custom message handler."""
        self._message_handlers[msg_type] = handler

    async def send_message(self, message: InterDeviceMessage) -> bool:
        """Send message to target device(s)."""
        if message.target_id == "broadcast":
            return await self._broadcast(message)
        else:
            return await self._send_to_device(message)

    async def _send_to_device(self, message: InterDeviceMessage) -> bool:
        """Send message to specific device."""
        if message.target_id not in self._network._connections:
            logger.warning(f"Target device not connected: {message.target_id}")
            return False

        websocket = self._network._connections[message.target_id]
        try:
            await websocket.send(json.dumps(message.to_dict()))

            if message.requires_ack:
                # Wait for acknowledgment
                future = asyncio.Future()
                self._pending_acks[message.message_id] = future
                try:
                    await asyncio.wait_for(future, timeout=10.0)
                    return True
                except asyncio.TimeoutError:
                    logger.warning(f"ACK timeout for message {message.message_id}")
                    return False
                finally:
                    self._pending_acks.pop(message.message_id, None)

            return True
        except Exception as e:
            logger.error(f"Failed to send message to {message.target_id}: {e}")
            return False

    async def _broadcast(self, message: InterDeviceMessage) -> bool:
        """Broadcast message to all connected devices."""
        sent = 0
        for device_id, websocket in self._network._connections.items():
            try:
                msg_copy = InterDeviceMessage(
                    message_id=f"{message.message_id}_{device_id}",
                    message_type=message.message_type,
                    source_id=message.source_id,
                    target_id=device_id,
                    payload=message.payload,
                    priority=message.priority,
                    timestamp=message.timestamp,
                    ttl=message.ttl,
                    requires_ack=False,
                    correlation_id=message.correlation_id,
                    metadata=message.metadata,
                )
                await websocket.send(json.dumps(msg_copy.to_dict()))
                sent += 1
            except Exception as e:
                logger.error(f"Broadcast failed to {device_id}: {e}")

        return sent > 0

    async def handle_incoming(self, device_id: str, data: Dict) -> None:
        """Handle incoming message from device."""
        try:
            message = InterDeviceMessage.from_dict(data)

            # Handle acknowledgment
            if message.message_type == MessageType.RESPONSE and message.correlation_id:
                if message.correlation_id in self._pending_acks:
                    future = self._pending_acks.pop(message.correlation_id)
                    if not future.done():
                        future.set_result(message.payload)
                    return

            # Route to handler
            handler = self._message_handlers.get(message.message_type)
            if handler:
                await handler(device_id, message)
            else:
                logger.warning(f"No handler for message type: {message.message_type}")

        except Exception as e:
            logger.error(f"Error handling incoming message: {e}")

    async def _handle_command(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle command message."""
        # Execute command and send response
        action = message.payload.get("action")
        params = message.payload.get("params", {})

        result = await self._network.send_command(device_id, action, params)

        if message.requires_ack:
            response = InterDeviceMessage(
                message_id=str(uuid.uuid4()),
                message_type=MessageType.RESPONSE,
                source_id=self._network.config.controller_id,
                target_id=device_id,
                payload=result,
                correlation_id=message.message_id,
            )
            await self.send_message(response)

    async def _handle_response(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle response message."""
        # Handled in handle_incoming for ACKs
        pass

    async def _handle_event(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle event message."""
        # Forward to event bus
        event_type = message.payload.get("event_type")
        event_data = message.payload.get("data", {})

        if event_type:
            from core.event_bus import Event
            event = Event(type=event_type, data=event_data, source=f"device:{device_id}")
            self._network._event_bus.emit(event) if self._network._event_bus else None

        # Notify subscribers
        await self._notify_subscribers(event_type, event_data, device_id)

    async def _handle_sync(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle sync message."""
        sync_type = message.payload.get("sync_type")

        if sync_type == "full":
            # Send full state
            state = {
                "devices": self._network.get_all_states() if hasattr(self._network, 'get_all_states') else {},
                "timestamp": time.time(),
            }
            response = InterDeviceMessage(
                message_id=str(uuid.uuid4()),
                message_type=MessageType.RESPONSE,
                source_id=self._network.config.controller_id,
                target_id=device_id,
                payload={"sync_type": "full", "state": state},
                correlation_id=message.message_id,
            )
            await self.send_message(response)

    async def _handle_heartbeat(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle heartbeat."""
        # Send ack
        response = InterDeviceMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.RESPONSE,
            source_id=self._network.config.controller_id,
            target_id=device_id,
            payload={"status": "alive", "timestamp": time.time()},
            correlation_id=message.message_id,
        )
        await self.send_message(response)

    async def _handle_state_update(self, device_id: str, message: InterDeviceMessage) -> None:
        """Handle state update from device."""
        # Update device state in synchronizer
        if hasattr(self._network, '_synchronizer'):
            self._network._synchronizer.update_state(device_id, message.payload)

    def subscribe(self, subscriber_id: str, event_types: List[str], filter: Dict = None) -> str:
        """Subscribe to events."""
        sub = Subscription(
            subscription_id=str(uuid.uuid4()),
            subscriber_id=subscriber_id,
            event_types=event_types,
            filter=filter or {},
        )

        for event_type in event_types:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            self._subscriptions[event_type].append(sub)

        return sub.subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from events."""
        for event_type, subs in self._subscriptions.items():
            for sub in subs:
                if sub.subscription_id == subscription_id:
                    subs.remove(sub)
                    return True
        return False

    async def _notify_subscribers(self, event_type: str, data: Dict, source: str) -> None:
        """Notify subscribers of event."""
        if event_type not in self._subscriptions:
            return

        for sub in self._subscriptions[event_type]:
            # Check filter
            match = True
            for key, value in sub.filter.items():
                if data.get(key) != value:
                    match = False
                    break

            if match:
                # Send to subscriber
                message = InterDeviceMessage(
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.EVENT,
                    source_id=source,
                    target_id=sub.subscriber_id,
                    payload={"event_type": event_type, "data": data},
                )
                await self.send_message(message)


class SyncManager:
    """
    Manages state synchronization across devices.
    """

    def __init__(self, network_manager: DeviceNetworkManager):
        self._network = network_manager
        self._sync_interval = 5.0
        self._running = False
        self._sync_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start sync manager."""
        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Sync Manager started")

    async def _sync_loop(self) -> None:
        """Periodic sync loop."""
        while self._running:
            try:
                await self._sync_all()
            except Exception as e:
                logger.error(f"Sync error: {e}")
            await asyncio.sleep(self._sync_interval)

    async def _sync_all(self) -> None:
        """Sync state with all devices."""
        for device_id in self._network._connections:
            await self._sync_device(device_id)

    async def _sync_device(self, device_id: str) -> None:
        """Sync with specific device."""
        if not hasattr(self._network, '_synchronizer'):
            return

        state = self._network._synchronizer.get_state(device_id)
        if state:
            message = InterDeviceMessage(
                message_id=str(uuid.uuid4()),
                message_type=MessageType.STATE_UPDATE,
                source_id=self._network.config.controller_id,
                target_id=device_id,
                payload=state,
            )
            await self._network._router.send_message(message)

    async def force_sync(self, device_id: str = None) -> None:
        """Force immediate sync."""
        if device_id:
            await self._sync_device(device_id)
        else:
            await self._sync_all()

    def set_sync_interval(self, interval: float) -> None:
        """Set sync interval."""
        self._sync_interval = interval

    async def stop(self) -> None:
        """Stop sync manager."""
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("Sync Manager stopped")


class InterDeviceComm:
    """
    High-level inter-device communication interface.
    Combines routing, sync, and high-level operations.
    """

    def __init__(self):
        self._network: Optional[DeviceNetworkManager] = None
        self._router: Optional[MessageRouter] = None
        self._sync: Optional[SyncManager] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize inter-device communication."""
        self._network = await get_device_network()
        self._router = MessageRouter(self._network)
        self._sync = SyncManager(self._network)
        await self._sync.start()
        self._initialized = True
        logger.info("Inter-Device Communication initialized")

    async def send_command(
        self,
        target_id: str,
        action: str,
        params: Dict = None,
        wait_response: bool = True,
        timeout: float = 30.0,
    ) -> Dict:
        """Send command to device."""
        if not self._initialized:
            await self.initialize()

        message = InterDeviceMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.COMMAND,
            source_id=self._network.config.controller_id,
            target_id=target_id,
            payload={"action": action, "params": params or {}},
            requires_ack=wait_response,
        )

        if wait_response:
            future = asyncio.Future()
            self._router._pending_acks[message.message_id] = future
            await self._router.send_message(message)
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                return {"success": False, "error": "Timeout"}
            finally:
                self._router._pending_acks.pop(message.message_id, None)
        else:
            await self._router.send_message(message)
            return {"success": True, "sent": True}

    async def broadcast_event(self, event_type: str, data: Dict) -> int:
        """Broadcast event to all devices."""
        if not self._initialized:
            await self.initialize()

        message = InterDeviceMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.BROADCAST,
            source_id=self._network.config.controller_id,
            target_id="broadcast",
            payload={"event_type": event_type, "data": data},
        )

        return await self._router.send_message(message)

    async def query_device(self, target_id: str, query: str, params: Dict = None) -> Dict:
        """Query device for information."""
        return await self.send_command(target_id, "query", {"query": query, "params": params or {}})

    async def sync_device(self, target_id: str) -> bool:
        """Force sync with device."""
        if not self._initialized:
            await self.initialize()
        await self._sync.force_sync(target_id)
        return True

    async def sync_all(self) -> None:
        """Force sync with all devices."""
        if not self._initialized:
            await self.initialize()
        await self._sync.force_sync()

    def subscribe(self, subscriber_id: str, event_types: List[str], filter: Dict = None) -> str:
        """Subscribe to device events."""
        if not self._router:
            return ""
        return self._router.subscribe(subscriber_id, event_types, filter)

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from events."""
        if not self._router:
            return False
        return self._router.unsubscribe(subscription_id)

    async def get_device_state(self, device_id: str) -> Optional[Dict]:
        """Get device state from synchronizer."""
        if hasattr(self._network, '_synchronizer'):
            return self._network._synchronizer.get_state(device_id)
        return None

    async def shutdown(self) -> None:
        """Shutdown inter-device communication."""
        if self._sync:
            await self._sync.stop()
        self._initialized = False
        logger.info("Inter-Device Communication shutdown")


# Global instance
_inter_device_comm: Optional[InterDeviceComm] = None


async def get_inter_device_comm() -> InterDeviceComm:
    """Get global inter-device communication instance."""
    global _inter_device_comm
    if _inter_device_comm is None:
        _inter_device_comm = InterDeviceComm()
        await _inter_device_comm.initialize()
    return _inter_device_comm