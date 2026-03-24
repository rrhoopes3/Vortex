"""P2P Network Layer for VortexChain.

Implements the gossip protocol and node discovery for VortexChain nodes.
Supports both classical TCP/IP networking and a future quantum channel
overlay for TopoQKD-secured inter-node communication.

Network topology:
  - Nodes form a structured overlay using Kademlia-style DHT
  - Blocks and transactions propagate via gossip
  - Validators maintain persistent connections for consensus messages
  - Quantum-capable nodes form a secondary QKD mesh for secure channels

Message types:
  - BLOCK_ANNOUNCE: New block propagation
  - TX_BROADCAST: Transaction broadcast
  - TOPOLOGY_CHALLENGE: Consensus PoT challenges
  - TOPOLOGY_RESPONSE: PoT challenge responses
  - PEER_DISCOVERY: Node discovery
  - QKD_HANDSHAKE: Quantum key establishment initiation
  - ENTROPY_REQUEST: Oracle entropy requests
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

class MessageType(Enum):
    BLOCK_ANNOUNCE = auto()
    TX_BROADCAST = auto()
    TOPOLOGY_CHALLENGE = auto()
    TOPOLOGY_RESPONSE = auto()
    PEER_DISCOVERY = auto()
    PEER_LIST = auto()
    QKD_HANDSHAKE = auto()
    ENTROPY_REQUEST = auto()
    ENTROPY_COMMIT = auto()
    ENTROPY_REVEAL = auto()
    PING = auto()
    PONG = auto()


# ---------------------------------------------------------------------------
# Network Message
# ---------------------------------------------------------------------------

@dataclass
class NetworkMessage:
    """A message in the VortexChain P2P network."""
    msg_type: MessageType
    sender: str                          # node ID of sender
    payload: Dict[str, Any]
    msg_id: bytes = field(default_factory=lambda: os.urandom(16))
    timestamp: float = field(default_factory=time.time)
    ttl: int = 10                        # max hops for gossip
    hop_count: int = 0

    def should_relay(self) -> bool:
        """Check if this message should be relayed further."""
        return self.hop_count < self.ttl

    def relay(self) -> "NetworkMessage":
        """Create a relay copy with incremented hop count."""
        return NetworkMessage(
            msg_type=self.msg_type,
            sender=self.sender,
            payload=self.payload,
            msg_id=self.msg_id,
            timestamp=self.timestamp,
            ttl=self.ttl,
            hop_count=self.hop_count + 1,
        )


# ---------------------------------------------------------------------------
# Peer Info
# ---------------------------------------------------------------------------

@dataclass
class PeerInfo:
    """Information about a peer node."""
    node_id: str
    address: str                         # IP:port or simulated address
    vx_address: str                      # VortexChain address
    is_validator: bool = False
    has_quantum: bool = False
    last_seen: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    reputation: float = 1.0

    @property
    def is_active(self) -> bool:
        """Check if peer was seen recently (within 5 minutes)."""
        return (time.time() - self.last_seen) < 300

    def update_seen(self) -> None:
        self.last_seen = time.time()


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class VortexNode:
    """A VortexChain P2P network node.

    Manages peer connections, message routing, and gossip propagation.
    In simulation mode, messages are delivered directly via method calls.
    """

    def __init__(
        self,
        node_id: str,
        vx_address: str,
        is_validator: bool = False,
        has_quantum: bool = False,
    ):
        self.node_id = node_id
        self.vx_address = vx_address
        self.is_validator = is_validator
        self.has_quantum = has_quantum

        # Peer management
        self.peers: Dict[str, PeerInfo] = {}
        self.max_peers: int = 50
        self._banned: Set[str] = set()

        # Message handling
        self._handlers: Dict[MessageType, List[Callable]] = {}
        self._seen_messages: Set[bytes] = set()
        self._max_seen: int = 10000

        # Metrics
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.messages_relayed: int = 0

        # Network reference (set when joining)
        self._network: Optional["VortexNetwork"] = None

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def add_peer(self, peer: PeerInfo) -> bool:
        """Add a peer to our peer table."""
        if peer.node_id == self.node_id:
            return False
        if peer.node_id in self._banned:
            return False
        if len(self.peers) >= self.max_peers:
            # Evict least-recently-seen peer
            self._evict_oldest_peer()
        self.peers[peer.node_id] = peer
        return True

    def remove_peer(self, node_id: str) -> None:
        """Remove a peer."""
        self.peers.pop(node_id, None)

    def ban_peer(self, node_id: str) -> None:
        """Ban a misbehaving peer."""
        self._banned.add(node_id)
        self.remove_peer(node_id)

    def _evict_oldest_peer(self) -> None:
        if not self.peers:
            return
        oldest = min(self.peers.values(), key=lambda p: p.last_seen)
        self.remove_peer(oldest.node_id)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def register_handler(
        self,
        msg_type: MessageType,
        handler: Callable[[NetworkMessage], None],
    ) -> None:
        """Register a handler for a message type."""
        self._handlers.setdefault(msg_type, []).append(handler)

    def receive_message(self, message: NetworkMessage) -> bool:
        """Receive and process an incoming message."""
        # Dedup
        if message.msg_id in self._seen_messages:
            return False

        self._seen_messages.add(message.msg_id)
        if len(self._seen_messages) > self._max_seen:
            # Prune oldest (just clear half — simple approach)
            seen_list = list(self._seen_messages)
            self._seen_messages = set(seen_list[len(seen_list) // 2:])

        self.messages_received += 1

        # Update peer last_seen
        if message.sender in self.peers:
            self.peers[message.sender].update_seen()

        # Dispatch to handlers
        handlers = self._handlers.get(message.msg_type, [])
        for handler in handlers:
            handler(message)

        # Gossip relay
        if message.should_relay():
            self._gossip_relay(message)

        return True

    def broadcast(self, msg_type: MessageType, payload: Dict[str, Any]) -> NetworkMessage:
        """Broadcast a message to all peers."""
        message = NetworkMessage(
            msg_type=msg_type,
            sender=self.node_id,
            payload=payload,
        )
        self._seen_messages.add(message.msg_id)

        if self._network:
            self._network.deliver(message, exclude={self.node_id})

        self.messages_sent += 1
        return message

    def send_to(
        self,
        target_id: str,
        msg_type: MessageType,
        payload: Dict[str, Any],
    ) -> Optional[NetworkMessage]:
        """Send a message to a specific peer."""
        if target_id not in self.peers and self._network:
            return None

        message = NetworkMessage(
            msg_type=msg_type,
            sender=self.node_id,
            payload=payload,
        )
        self._seen_messages.add(message.msg_id)

        if self._network:
            self._network.deliver_to(target_id, message)

        self.messages_sent += 1
        return message

    def _gossip_relay(self, message: NetworkMessage) -> None:
        """Relay a message to peers via gossip."""
        if not self._network:
            return

        relayed = message.relay()
        self._network.deliver(relayed, exclude={self.node_id, message.sender})
        self.messages_relayed += 1

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def request_peers(self) -> None:
        """Request peer lists from connected peers."""
        self.broadcast(MessageType.PEER_DISCOVERY, {
            "requesting_node": self.node_id,
            "known_peers": list(self.peers.keys()),
        })

    def get_peer_info(self) -> PeerInfo:
        """Get this node's peer info for sharing."""
        return PeerInfo(
            node_id=self.node_id,
            address=f"sim://{self.node_id}",
            vx_address=self.vx_address,
            is_validator=self.is_validator,
            has_quantum=self.has_quantum,
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def peer_count(self) -> int:
        return len(self.peers)

    @property
    def active_peer_count(self) -> int:
        return sum(1 for p in self.peers.values() if p.is_active)

    @property
    def quantum_peer_count(self) -> int:
        return sum(1 for p in self.peers.values() if p.has_quantum)


# ---------------------------------------------------------------------------
# Network Simulation
# ---------------------------------------------------------------------------

class VortexNetwork:
    """Simulated VortexChain P2P network.

    In production, this would be replaced by real TCP/IP connections.
    The simulation enables testing of gossip propagation, consensus
    messaging, and network topology without actual sockets.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, VortexNode] = {}
        self.total_messages: int = 0
        self._message_log: List[NetworkMessage] = []
        self._max_log: int = 10000

    def add_node(self, node: VortexNode) -> None:
        """Add a node to the network."""
        node._network = self
        self.nodes[node.node_id] = node

        # Auto-discover existing nodes
        for existing_id, existing_node in self.nodes.items():
            if existing_id != node.node_id:
                node.add_peer(existing_node.get_peer_info())
                existing_node.add_peer(node.get_peer_info())

    def remove_node(self, node_id: str) -> None:
        """Remove a node from the network."""
        node = self.nodes.pop(node_id, None)
        if node:
            node._network = None
            # Remove from all peer tables
            for other in self.nodes.values():
                other.remove_peer(node_id)

    def deliver(self, message: NetworkMessage, exclude: Optional[Set[str]] = None) -> int:
        """Deliver a message to all nodes (except excluded)."""
        exclude = exclude or set()
        delivered = 0

        for node_id, node in self.nodes.items():
            if node_id not in exclude:
                if node.receive_message(message):
                    delivered += 1

        self.total_messages += 1
        if len(self._message_log) < self._max_log:
            self._message_log.append(message)

        return delivered

    def deliver_to(self, target_id: str, message: NetworkMessage) -> bool:
        """Deliver a message to a specific node."""
        node = self.nodes.get(target_id)
        if node is None:
            return False
        self.total_messages += 1
        return node.receive_message(message)

    # ------------------------------------------------------------------
    # Network queries
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def validator_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.is_validator)

    @property
    def quantum_node_count(self) -> int:
        return sum(1 for n in self.nodes.values() if n.has_quantum)

    def get_validators(self) -> List[VortexNode]:
        return [n for n in self.nodes.values() if n.is_validator]

    def get_quantum_nodes(self) -> List[VortexNode]:
        return [n for n in self.nodes.values() if n.has_quantum]

    def network_stats(self) -> Dict[str, Any]:
        """Get network-wide statistics."""
        return {
            "total_nodes": self.node_count,
            "validators": self.validator_count,
            "quantum_nodes": self.quantum_node_count,
            "total_messages": self.total_messages,
            "avg_peers_per_node": (
                sum(n.peer_count for n in self.nodes.values()) / max(1, self.node_count)
            ),
        }
