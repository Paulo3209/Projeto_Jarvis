"""
State Synchronizer - Synchronizes state across distributed JARVIS devices.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SyncType(Enum):
    """Types of synchronization."""
    FULL = "full"           # Full state sync
    INCREMENTAL = "incremental"  # Incremental updates
    EVENT = "event"         # Event-based sync


@dataclass
class SyncConfig:
    """Synchronization configuration."""
    sync_interval: int = 5
    max_batch_size: int = 100
    conflict_resolution: str = "controller_wins"  # controller_wins, latest_wins, merge
    sync_types: List[SyncType] = field(default_factory=lambda: [SyncType.INCREMENTAL, SyncType.EVENT])
    persist_state: bool = True
    state_file: str = "device_network_state.json"


@dataclass
class StateSnapshot:
    """Snapshot of device state."""
    device_id: str
    timestamp: float
    state: Dict[str, Any]
    version: int = 0


class StateSynchronizer:
    """
    Synchronizes state across the device network.
    Handles conflict resolution, incremental updates, and persistence.
    """

    def __init__(self, config: Optional[SyncConfig] = None):
        self.config = config or SyncConfig()
        self._states: Dict[str, StateSnapshot] = {}
        self._pending_updates: Dict[str, List[Dict]] = {}
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._running = False
        self._version_counter = 0

    async def initialize(self) -> None:
        """Initialize synchronizer."""
        if self.config.persist_state:
            await self._load_state()
        self._running = True
        asyncio.create_task(self._sync_loop())
        logger.info("State synchronizer initialized")

    async def _load_state(self) -> None:
        """Load persisted state."""
        try:
            import aiofiles
            async with aiofiles.open(self.config.state_file, 'r') as f:
                content = await f.read()
                data = json.loads(content)
                for device_id, snapshot_data in data.items():
                    self._states[device_id] = StateSnapshot(**snapshot_data)
                    self._version_counter = max(self._version_counter, snapshot_data.get("version", 0))
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    async def _save_state(self) -> None:
        """Persist state to disk."""
        if not self.config.persist_state:
            return

        try:
            import aiofiles
            data = {
                device_id: {
                    "device_id": snap.device_id,
                    "timestamp": snap.timestamp,
                    "state": snap.state,
                    "version": snap.version,
                }
                for device_id, snap in self._states.items()
            }
            async with aiofiles.open(self.config.state_file, 'w') as f:
                await f.write(json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def subscribe(self, device_id: str, callback: Callable[[Dict], None]) -> None:
        """Subscribe to state changes for a device."""
        if device_id not in self._subscribers:
            self._subscribers[device_id] = set()
        self._subscribers[device_id].add(callback)

    def unsubscribe(self, device_id: str, callback: Callable[[Dict], None]) -> None:
        """Unsubscribe from state changes."""
        if device_id in self._subscribers:
            self._subscribers[device_id].discard(callback)

    def update_state(self, device_id: str, state: Dict, source: str = "local") -> None:
        """Update device state."""
        self._version_counter += 1

        if device_id not in self._states:
            self._states[device_id] = StateSnapshot(
                device_id=device_id,
                timestamp=time.time(),
                state={},
                version=0,
            )

        snapshot = self._states[device_id]
        old_state = snapshot.state.copy()

        # Merge states based on conflict resolution
        merged_state = self._merge_states(old_state, state, source)
        snapshot.state = merged_state
        snapshot.timestamp = time.time()
        snapshot.version = self._version_counter

        # Notify subscribers
        if device_id in self._subscribers:
            for callback in self._subscribers[device_id]:
                try:
                    callback(merged_state)
                except Exception as e:
                    logger.error(f"Subscriber callback error: {e}")

        # Queue for sync
        if SyncType.INCREMENTAL in self.config.sync_types:
            if device_id not in self._pending_updates:
                self._pending_updates[device_id] = []
            self._pending_updates[device_id].append({
                "state": merged_state,
                "version": self._version_counter,
                "timestamp": time.time(),
            })

    def _merge_states(self, old: Dict, new: Dict, source: str) -> Dict:
        """Merge states based on conflict resolution strategy."""
        if self.config.conflict_resolution == "controller_wins":
            # Controller (source="controller") always wins
            if source == "controller":
                return {**old, **new}
            return old

        elif self.config.conflict_resolution == "latest_wins":
            # Latest timestamp wins (simplified - just use new)
            return {**old, **new}

        elif self.config.conflict_resolution == "merge":
            # Deep merge
            result = old.copy()
            for key, value in new.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = self._merge_states(result[key], value, source)
                else:
                    result[key] = value
            return result

        return {**old, **new}

    def get_state(self, device_id: str) -> Optional[Dict]:
        """Get current state for device."""
        if device_id in self._states:
            return self._states[device_id].state.copy()
        return None

    def get_all_states(self) -> Dict[str, Dict]:
        """Get all device states."""
        return {
            device_id: snap.state.copy()
            for device_id, snap in self._states.items()
        }

    def get_version(self, device_id: str) -> int:
        """Get state version for device."""
        if device_id in self._states:
            return self._states[device_id].version
        return 0

    async def _sync_loop(self) -> None:
        """Periodic sync loop."""
        while self._running:
            await asyncio.sleep(self.config.sync_interval)

            # Process pending updates
            if self._pending_updates:
                await self._process_pending_updates()

            # Persist state
            if self.config.persist_state:
                await self._save_state()

    async def _process_pending_updates(self) -> None:
        """Process pending updates for sync."""
        # This would send updates to other devices
        # For now, just clear old pending updates
        cutoff = time.time() - 300  # 5 minutes
        for device_id, updates in list(self._pending_updates.items()):
            self._pending_updates[device_id] = [
                u for u in updates if u["timestamp"] > cutoff
            ]
            if not self._pending_updates[device_id]:
                del self._pending_updates[device_id]

    async def request_sync(self, device_id: str, sync_type: SyncType = SyncType.FULL) -> Dict:
        """Request sync from a device."""
        if device_id not in self._states:
            return {"success": False, "error": "Device not known"}

        snapshot = self._states[device_id]
        return {
            "success": True,
            "device_id": device_id,
            "state": snapshot.state,
            "version": snapshot.version,
            "timestamp": snapshot.timestamp,
        }

    async def broadcast_event(self, event_type: str, data: Dict, source_device: str) -> None:
        """Broadcast event to all subscribers."""
        if SyncType.EVENT in self.config.sync_types:
            for device_id, subscribers in self._subscribers.items():
                if device_id != source_device:
                    for callback in subscribers:
                        try:
                            await callback({
                                "type": "event",
                                "event_type": event_type,
                                "data": data,
                                "source": source_device,
                                "timestamp": time.time(),
                            })
                        except Exception as e:
                            logger.error(f"Event broadcast error: {e}")

    async def shutdown(self) -> None:
        """Shutdown synchronizer."""
        self._running = False
        if self.config.persist_state:
            await self._save_state()
        logger.info("State synchronizer shutdown")