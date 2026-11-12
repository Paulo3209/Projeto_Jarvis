"""
Device Network Module - Smart device network for JARVIS.
Manages agents on authorized computers, phones, TVs, and IoT devices.
"""
from .manager import DeviceNetworkManager, NetworkConfig, get_device_network
from .agent import NetworkAgent, AgentConfig, AgentStatus
from .discovery import NetworkDiscovery, DiscoveryConfig
from .sync import StateSynchronizer, SyncConfig

__all__ = [
    "DeviceNetworkManager",
    "NetworkConfig",
    "get_device_network",
    "NetworkAgent",
    "AgentConfig",
    "AgentStatus",
    "NetworkDiscovery",
    "DiscoveryConfig",
    "StateSynchronizer",
    "SyncConfig",
]