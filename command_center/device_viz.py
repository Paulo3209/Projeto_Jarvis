"""
Device Visualizer - Network topology and device visualization.
Shows device relationships, status, and network map.
"""
from __future__ import annotations
import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from devices.device_registry import get_device_manager, Device, DeviceType, ConnectionProtocol, ConnectionStatus

logger = logging.getLogger(__name__)


class LayoutAlgorithm(Enum):
    """Graph layout algorithms."""
    FORCE_DIRECTED = "force_directed"
    CIRCULAR = "circular"
    HIERARCHICAL = "hierarchical"
    GRID = "grid"
    RADIAL = "radial"


@dataclass
class DeviceNode:
    """Device node for visualization."""
    device_id: str
    name: str
    device_type: DeviceType
    protocol: ConnectionProtocol
    status: ConnectionStatus
    position: Tuple[float, float] = (0.0, 0.0)
    size: float = 1.0
    color: str = "#00ff88"
    label: str = ""
    metadata: Dict = field(default_factory=dict)


@dataclass
class DeviceLink:
    """Link between devices."""
    source_id: str
    target_id: str
    link_type: str = "connected"
    strength: float = 1.0
    color: str = "#00ff8888"
    animated: bool = False


@dataclass
class DeviceMap:
    """Complete device map."""
    nodes: List[DeviceNode]
    links: List[DeviceLink]
    bounds: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    layout: LayoutAlgorithm
    generated_at: datetime = field(default_factory=datetime.now)


@dataclass
class NetworkTopology:
    """Network topology analysis."""
    clusters: List[List[str]]  # Device IDs in each cluster
    central_devices: List[str]  # Most connected devices
    isolated_devices: List[str]  # Devices with no connections
    topology_type: str  # star, mesh, tree, ring, hybrid
    diameter: int  # Longest shortest path
    avg_path_length: float
    density: float  # Edge density


class DeviceVisualizer:
    """
    Visualizes device network topology.
    Generates interactive maps and network analysis.
    """

    def __init__(self):
        self._manager = get_device_manager()
        self._layout_algo = LayoutAlgorithm.FORCE_DIRECTED
        self._cache: Optional[DeviceMap] = None
        self._cache_time = 0
        self._cache_ttl = 5.0

    def set_layout_algorithm(self, algo: LayoutAlgorithm) -> None:
        """Set layout algorithm."""
        self._layout_algo = algo
        self._cache = None

    async def generate_map(self, force_refresh: bool = False) -> DeviceMap:
        """Generate device map."""
        if not force_refresh and self._cache and time.time() - self._cache_time < self._cache_ttl:
            return self._cache

        devices = self._manager.list_devices()
        nodes = []
        links = []

        # Create nodes
        for device in devices:
            node = self._device_to_node(device)
            nodes.append(node)

        # Create links based on relationships
        links = self._generate_links(nodes)

        # Apply layout
        if self._layout_algo == LayoutAlgorithm.FORCE_DIRECTED:
            nodes = await self._force_directed_layout(nodes, links)
        elif self._layout_algo == LayoutAlgorithm.CIRCULAR:
            nodes = self._circular_layout(nodes)
        elif self._layout_algo == LayoutAlgorithm.HIERARCHICAL:
            nodes = self._hierarchical_layout(nodes, links)
        elif self._layout_algo == LayoutAlgorithm.GRID:
            nodes = self._grid_layout(nodes)
        elif self._layout_algo == LayoutAlgorithm.RADIAL:
            nodes = self._radial_layout(nodes)

        # Calculate bounds
        bounds = self._calculate_bounds(nodes)

        device_map = DeviceMap(
            nodes=nodes,
            links=links,
            bounds=bounds,
            layout=self._layout_algo,
        )

        self._cache = device_map
        self._cache_time = time.time()

        return device_map

    def _device_to_node(self, device: Device) -> DeviceNode:
        """Convert device to visualization node."""
        # Color by status
        status_colors = {
            ConnectionStatus.CONNECTED: "#00ff88",
            ConnectionStatus.CONNECTING: "#ffaa00",
            ConnectionStatus.DISCONNECTED: "#888888",
            ConnectionStatus.ERROR: "#ff4444",
            ConnectionStatus.BLOCKED: "#ff0000",
        }

        # Size by type importance
        type_sizes = {
            DeviceType.COMPUTER: 1.5,
            DeviceType.ANDROID: 1.2,
            DeviceType.SMART_TV: 1.0,
            DeviceType.IOT_SENSOR: 0.7,
            DeviceType.IOT_ACTUATOR: 0.7,
            DeviceType.ROUTER: 1.3,
            DeviceType.SERVER: 1.5,
        }

        # Type icons/labels
        type_labels = {
            DeviceType.COMPUTER: "🖥",
            DeviceType.ANDROID: "📱",
            DeviceType.SMART_TV: "📺",
            DeviceType.IOT_SENSOR: "📡",
            DeviceType.IOT_ACTUATOR: "⚙",
            DeviceType.ROUTER: "🌐",
            DeviceType.SERVER: "🗄",
        }

        return DeviceNode(
            device_id=device.device_id,
            name=device.name,
            device_type=device.device_type,
            protocol=device.protocol,
            status=device.connection_status,
            color=status_colors.get(device.connection_status, "#888888"),
            size=type_sizes.get(device.device_type, 1.0),
            label=type_labels.get(device.device_type, "?"),
            metadata={
                "address": device.address,
                "port": device.port,
                "trusted": device.trusted,
                "capabilities": [c.value for c in device.capabilities],
            }
        )

    def _generate_links(self, nodes: List[DeviceNode]) -> List[DeviceLink]:
        """Generate links between devices."""
        links = []
        device_map = {n.device_id: n for n in nodes}

        # Get actual devices for relationship info
        for node in nodes:
            device = self._manager.get_device(node.device_id)
            if not device:
                continue

            # Link to controller (this machine)
            if device.protocol in [ConnectionProtocol.ADB, ConnectionProtocol.SSH, ConnectionProtocol.HTTP]:
                links.append(DeviceLink(
                    source_id="controller",
                    target_id=node.device_id,
                    link_type="control",
                    strength=1.0,
                    color="#00ffff88",
                ))

            # Link devices on same network
            for other_node in nodes:
                if other_node.device_id == node.device_id:
                    continue
                other_device = self._manager.get_device(other_node.device_id)
                if not other_device:
                    continue

                # Same subnet
                if self._same_subnet(device.address, other_device.address):
                    links.append(DeviceLink(
                        source_id=node.device_id,
                        target_id=other_node.device_id,
                        link_type="network",
                        strength=0.5,
                        color="#8888ff88",
                    ))

                # Same protocol type
                if device.protocol == other_device.protocol:
                    links.append(DeviceLink(
                        source_id=node.device_id,
                        target_id=other_node.device_id,
                        link_type="protocol",
                        strength=0.3,
                        color="#ff88ff88",
                    ))

        return links

    def _same_subnet(self, addr1: str, addr2: str, prefix: int = 24) -> bool:
        """Check if two addresses are in same subnet."""
        try:
            import ipaddress
            ip1 = ipaddress.ip_address(addr1.split(':')[0])
            ip2 = ipaddress.ip_address(addr2.split(':')[0])
            network1 = ipaddress.ip_network(f"{ip1}/{prefix}", strict=False)
            network2 = ipaddress.ip_network(f"{ip2}/{prefix}", strict=False)
            return network1 == network2
        except Exception:
            return False

    async def _force_directed_layout(
        self,
        nodes: List[DeviceNode],
        links: List[DeviceLink],
        iterations: int = 50,
    ) -> List[DeviceNode]:
        """Force-directed graph layout (simplified)."""
        if not nodes:
            return nodes

        # Initialize positions randomly
        import random
        for node in nodes:
            if node.position == (0.0, 0.0):
                node.position = (random.uniform(-1, 1), random.uniform(-1, 1))

        node_map = {n.device_id: n for n in nodes}

        # Simple force-directed simulation
        for _ in range(iterations):
            forces = {n.device_id: [0.0, 0.0] for n in nodes}

            # Repulsion between all nodes
            for i, n1 in enumerate(nodes):
                for n2 in nodes[i+1:]:
                    dx = n1.position[0] - n2.position[0]
                    dy = n1.position[1] - n2.position[1]
                    dist = max(0.01, math.sqrt(dx*dx + dy*dy))
                    force = 0.01 / (dist * dist)
                    fx = force * dx / dist
                    fy = force * dy / dist
                    forces[n1.device_id][0] += fx
                    forces[n1.device_id][1] += fy
                    forces[n2.device_id][0] -= fx
                    forces[n2.device_id][1] -= fy

            # Attraction for links
            for link in links:
                n1 = node_map.get(link.source_id)
                n2 = node_map.get(link.target_id)
                if not n1 or not n2:
                    continue
                dx = n2.position[0] - n1.position[0]
                dy = n2.position[1] - n1.position[1]
                dist = max(0.01, math.sqrt(dx*dx + dy*dy))
                force = 0.01 * dist * link.strength
                fx = force * dx / dist
                fy = force * dy / dist
                forces[n1.device_id][0] += fx
                forces[n1.device_id][1] += fy
                forces[n2.device_id][0] -= fx
                forces[n2.device_id][1] -= fy

            # Apply forces
            for node in nodes:
                fx, fy = forces[node.device_id]
                node.position = (
                    node.position[0] + fx * 0.1,
                    node.position[1] + fy * 0.1
                )

        return nodes

    def _circular_layout(self, nodes: List[DeviceNode]) -> List[DeviceNode]:
        """Circular layout."""
        if not nodes:
            return nodes

        center_x, center_y = 0.0, 0.0
        radius = 1.0
        angle_step = 2 * math.pi / len(nodes)

        for i, node in enumerate(nodes):
            angle = i * angle_step
            node.position = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle)
            )

        return nodes

    def _hierarchical_layout(
        self,
        nodes: List[DeviceNode],
        links: List[DeviceLink],
    ) -> List[DeviceNode]:
        """Hierarchical layout (tree-like)."""
        # Find root (controller or most connected)
        device_map = {n.device_id: n for n in nodes}

        # Build adjacency
        adj = {n.device_id: [] for n in nodes}
        for link in links:
            if link.source_id in adj and link.target_id in adj:
                adj[link.source_id].append(link.target_id)

        # Find roots (nodes with no incoming links)
        has_incoming = set()
        for link in links:
            has_incoming.add(link.target_id)

        roots = [n.device_id for n in nodes if n.device_id not in has_incoming]
        if not roots:
            roots = [nodes[0].device_id]

        # BFS layout
        level = 0
        queue = [(root, 0) for root in roots]
        visited = set()
        x_positions = {}

        while queue:
            node_id, lvl = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            if lvl not in x_positions:
                x_positions[lvl] = 0

            node = device_map.get(node_id)
            if node:
                node.position = (x_positions[lvl] * 2.0 - len(x_positions), -lvl * 1.5)
                x_positions[lvl] += 1

            for neighbor in adj.get(node_id, []):
                if neighbor not in visited:
                    queue.append((neighbor, lvl + 1))

        return nodes

    def _grid_layout(self, nodes: List[DeviceNode]) -> List[DeviceNode]:
        """Grid layout."""
        if not nodes:
            return nodes

        cols = math.ceil(math.sqrt(len(nodes)))
        spacing = 2.0

        for i, node in enumerate(nodes):
            row = i // cols
            col = i % cols
            node.position = (
                col * spacing - (cols - 1) * spacing / 2,
                row * spacing - (math.ceil(len(nodes) / cols) - 1) * spacing / 2
            )

        return nodes

    def _radial_layout(self, nodes: List[DeviceNode]) -> List[DeviceNode]:
        """Radial layout with controller at center."""
        if not nodes:
            return nodes

        # Put controller at center
        controller_node = None
        other_nodes = []

        for node in nodes:
            device = self._manager.get_device(node.device_id)
            if device and device.protocol in [ConnectionProtocol.ADB, ConnectionProtocol.SSH]:
                controller_node = node
            else:
                other_nodes.append(node)

        if controller_node:
            controller_node.position = (0.0, 0.0)

        if not other_nodes:
            return nodes

        # Arrange others in circles
        rings = 1
        while rings * 6 < len(other_nodes):
            rings += 1

        idx = 0
        for ring in range(1, rings + 1):
            count = min(6 * ring, len(other_nodes) - idx)
            radius = ring * 1.5
            angle_step = 2 * math.pi / count

            for i in range(count):
                if idx >= len(other_nodes):
                    break
                angle = i * angle_step
                other_nodes[idx].position = (
                    radius * math.cos(angle),
                    radius * math.sin(angle)
                )
                idx += 1

        return nodes

    def _calculate_bounds(self, nodes: List[DeviceNode]) -> Tuple[float, float, float, float]:
        """Calculate bounding box."""
        if not nodes:
            return (-1, -1, 1, 1)

        min_x = min(n.position[0] for n in nodes)
        max_x = max(n.position[0] for n in nodes)
        min_y = min(n.position[1] for n in nodes)
        max_y = max(n.position[1] for n in nodes)

        # Add padding
        padding = 0.5
        return (
            min_x - padding, min_y - padding,
            max_x + padding, max_y + padding
        )

    def analyze_topology(self, device_map: DeviceMap = None) -> NetworkTopology:
        """Analyze network topology."""
        if device_map is None:
            device_map = asyncio.run(self.generate_map())

        nodes = {n.device_id: n for n in device_map.nodes}
        links = device_map.links

        # Build adjacency
        adj = {nid: set() for nid in nodes}
        for link in links:
            if link.source_id in adj and link.target_id in adj:
                adj[link.source_id].add(link.target_id)
                adj[link.target_id].add(link.source_id)

        # Find clusters (connected components)
        visited = set()
        clusters = []

        for node_id in nodes:
            if node_id not in visited:
                cluster = []
                stack = [node_id]
                while stack:
                    current = stack.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    cluster.append(current)
                    for neighbor in adj.get(current, []):
                        if neighbor not in visited:
                            stack.append(neighbor)
                clusters.append(cluster)

        # Find central devices (highest degree)
        degrees = {nid: len(neighbors) for nid, neighbors in adj.items()}
        central = sorted(degrees.keys(), key=lambda x: degrees[x], reverse=True)[:3]

        # Find isolated devices
        isolated = [nid for nid, deg in degrees.items() if deg == 0]

        # Determine topology type
        topology_type = self._classify_topology(adj, degrees)

        # Calculate diameter and avg path length
        diameter, avg_path = self._calculate_paths(adj)

        # Density
        n = len(nodes)
        max_edges = n * (n - 1) / 2
        actual_edges = sum(len(neighbors) for neighbors in adj.values()) / 2
        density = actual_edges / max_edges if max_edges > 0 else 0

        return NetworkTopology(
            clusters=clusters,
            central_devices=central,
            isolated_devices=isolated,
            topology_type=topology_type,
            diameter=diameter,
            avg_path_length=avg_path,
            density=density,
        )

    def _classify_topology(self, adj: Dict, degrees: Dict) -> str:
        """Classify network topology."""
        n = len(adj)
        if n <= 1:
            return "single"

        max_deg = max(degrees.values()) if degrees else 0
        avg_deg = sum(degrees.values()) / n if n > 0 else 0

        if max_deg == n - 1 and avg_deg > n * 0.7:
            return "star"
        elif avg_deg > n * 0.5:
            return "mesh"
        elif max_deg <= 2:
            return "ring"
        elif max_deg <= 3 and avg_deg < 2:
            return "tree"
        else:
            return "hybrid"

    def _calculate_paths(self, adj: Dict) -> Tuple[int, float]:
        """Calculate diameter and average path length."""
        nodes = list(adj.keys())
        if len(nodes) < 2:
            return 0, 0.0

        all_paths = []

        for source in nodes:
            # BFS for shortest paths
            distances = {source: 0}
            queue = [source]

            while queue:
                current = queue.pop(0)
                for neighbor in adj.get(current, []):
                    if neighbor not in distances:
                        distances[neighbor] = distances[current] + 1
                        queue.append(neighbor)

            for target, dist in distances.items():
                if target != source:
                    all_paths.append(dist)

        if not all_paths:
            return 0, 0.0

        return max(all_paths), sum(all_paths) / len(all_paths)

    def get_device_info(self, device_id: str) -> Optional[Dict]:
        """Get detailed device info for visualization."""
        device = self._manager.get_device(device_id)
        if not device:
            return None

        return {
            "device_id": device.device_id,
            "name": device.name,
            "type": device.device_type.value,
            "protocol": device.protocol.value,
            "status": device.connection_status.value,
            "address": device.address,
            "port": device.port,
            "trusted": device.trusted,
            "capabilities": [c.value for c in device.capabilities],
            "metadata": device.metadata,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        }


# Global instance
_device_visualizer: Optional[DeviceVisualizer] = None


def get_device_visualizer() -> DeviceVisualizer:
    """Get global device visualizer."""
    global _device_visualizer
    if _device_visualizer is None:
        _device_visualizer = DeviceVisualizer()
    return _device_visualizer