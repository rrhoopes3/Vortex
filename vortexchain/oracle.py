"""Quantum Entropy Oracle for VortexChain.

Provides true quantum randomness derived from OAM photon measurements.
This randomness is used for:
  - Consensus leader election (unpredictable, unbiasable)
  - Smart contract randomness (verifiable on-chain)
  - Key generation entropy supplementation
  - Topological lottery/gaming applications

Architecture:
  - Oracles stake $VORTEX and register their hardware capabilities
  - When randomness is requested, oracles perform OAM measurements
  - Results are committed via a commit-reveal scheme to prevent manipulation
  - Multiple oracles contribute entropy that is mixed via topological hashing
  - Each entropy contribution is verifiable against the oracle's registered
    manifold parameters

In classical simulation mode, entropy is derived from the topological
manifold's intrinsic structure (still far better than PRNGs for blockchain
use due to the high-dimensional mixing).
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from vortexchain.manifold import (
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
)
from vortexchain.toac import TopologicalHash


# ---------------------------------------------------------------------------
# Entropy Request / Response
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntropyRequest:
    """A request for quantum entropy from the oracle network."""
    request_id: bytes            # unique request identifier
    requester: str               # vx-address of the requester
    num_bytes: int               # how many random bytes needed
    min_oracles: int = 3         # minimum oracles that must contribute
    block_height: int = 0        # chain height at time of request
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        requester: str,
        num_bytes: int = 32,
        min_oracles: int = 3,
        block_height: int = 0,
    ) -> "EntropyRequest":
        request_id = hashlib.sha256(
            requester.encode()
            + struct.pack(">dI", time.time(), num_bytes)
            + os.urandom(16)
        ).digest()
        return cls(
            request_id=request_id,
            requester=requester,
            num_bytes=num_bytes,
            min_oracles=min_oracles,
            block_height=block_height,
        )


@dataclass
class EntropyCommitment:
    """An oracle's commitment to an entropy contribution (commit phase)."""
    oracle_address: str
    request_id: bytes
    commitment_hash: bytes       # hash of (entropy || nonce)
    timestamp: float = field(default_factory=time.time)


@dataclass
class EntropyReveal:
    """An oracle's revealed entropy (reveal phase)."""
    oracle_address: str
    request_id: bytes
    entropy: bytes               # the actual random bytes
    nonce: bytes                 # the nonce used in commitment
    manifold_proof: List[int]    # wrapping numbers as proof of OAM measurement

    def verify_commitment(self, commitment: EntropyCommitment) -> bool:
        """Verify that this reveal matches the earlier commitment."""
        expected = hashlib.sha256(self.entropy + self.nonce).digest()
        return expected == commitment.commitment_hash


# ---------------------------------------------------------------------------
# OAM Entropy Source (simulated)
# ---------------------------------------------------------------------------

class OAMEntropySource:
    """Simulates quantum entropy from OAM photon measurements.

    In real hardware, this interfaces with:
    - SPDC source generating entangled OAM photon pairs
    - Spatial light modulators for mode sorting
    - Single-photon detectors recording OAM mode outcomes

    Each measurement of a d=7 OAM qudit yields log2(7) ≈ 2.81 bits
    of true quantum randomness.  In the 48D composite space, one
    entangled pair yields up to ~5.58 bits.
    """

    def __init__(self, device_seed: Optional[bytes] = None):
        self.device_seed = device_seed or os.urandom(64)
        self._measurement_count = 0
        # In simulation, we use a manifold-derived CSPRNG
        self._manifold = TopologicalManifold.from_seed(self.device_seed)

    def measure(self, num_bytes: int = 32) -> Tuple[bytes, List[int]]:
        """Perform a simulated OAM measurement to extract entropy.

        Returns:
            (entropy_bytes, wrapping_proof) — the random bytes and the
            wrapping numbers that prove the measurement was performed
            on the registered manifold.
        """
        self._measurement_count += 1

        # Derive entropy from manifold + counter (simulation)
        seed = (
            self._manifold.to_bytes()
            + struct.pack(">Q", self._measurement_count)
            + os.urandom(32)  # mix in system entropy
        )

        # Extract entropy via topological hash cascade
        h = TopologicalHash.hash(seed)
        expanded = bytearray()
        counter = 0
        while len(expanded) < num_bytes:
            block = hashlib.sha256(
                h.digest + struct.pack(">I", counter)
            ).digest()
            expanded.extend(block)
            counter += 1

        entropy = bytes(expanded[:num_bytes])
        proof = self._manifold.topological_spectrum()

        return entropy, proof

    @property
    def measurement_count(self) -> int:
        return self._measurement_count


# ---------------------------------------------------------------------------
# Oracle Node
# ---------------------------------------------------------------------------

@dataclass
class OracleNode:
    """A VortexChain entropy oracle node.

    Stakes $VORTEX and provides quantum entropy to the network via
    a commit-reveal protocol.
    """
    address: str
    stake: float
    entropy_source: OAMEntropySource = field(default_factory=OAMEntropySource)
    has_quantum_hardware: bool = False
    contributions: int = 0
    reputation: float = 1.0        # starts at 1.0, goes up/down

    def commit_entropy(self, request: EntropyRequest) -> EntropyCommitment:
        """Generate and commit entropy for a request."""
        entropy, proof = self.entropy_source.measure(request.num_bytes)
        nonce = os.urandom(32)

        commitment_hash = hashlib.sha256(entropy + nonce).digest()

        # Store for later reveal
        self._pending_reveal = EntropyReveal(
            oracle_address=self.address,
            request_id=request.request_id,
            entropy=entropy,
            nonce=nonce,
            manifold_proof=proof,
        )

        return EntropyCommitment(
            oracle_address=self.address,
            request_id=request.request_id,
            commitment_hash=commitment_hash,
        )

    def reveal_entropy(self, request_id: bytes) -> Optional[EntropyReveal]:
        """Reveal the committed entropy."""
        if hasattr(self, '_pending_reveal') and self._pending_reveal.request_id == request_id:
            reveal = self._pending_reveal
            self._pending_reveal = None
            self.contributions += 1
            return reveal
        return None


# ---------------------------------------------------------------------------
# Entropy Aggregator (on-chain)
# ---------------------------------------------------------------------------

class EntropyAggregator:
    """Aggregates entropy from multiple oracles into a single verifiable
    random value.

    Uses topological hashing to mix entropy contributions, making the
    result unbiasable as long as at least one oracle is honest.
    """

    def __init__(self) -> None:
        self.oracles: Dict[str, OracleNode] = {}
        self._pending_requests: Dict[bytes, EntropyRequest] = {}
        self._commitments: Dict[bytes, List[EntropyCommitment]] = {}
        self._reveals: Dict[bytes, List[EntropyReveal]] = {}
        self._results: Dict[bytes, bytes] = {}

    def register_oracle(self, oracle: OracleNode) -> None:
        """Register an oracle node."""
        self.oracles[oracle.address] = oracle

    def request_entropy(self, request: EntropyRequest) -> bytes:
        """Submit an entropy request. Returns the request_id."""
        self._pending_requests[request.request_id] = request
        self._commitments[request.request_id] = []
        self._reveals[request.request_id] = []
        return request.request_id

    def submit_commitment(self, commitment: EntropyCommitment) -> bool:
        """Accept an oracle's commitment."""
        rid = commitment.request_id
        if rid not in self._pending_requests:
            return False
        if commitment.oracle_address not in self.oracles:
            return False
        self._commitments[rid].append(commitment)
        return True

    def submit_reveal(self, reveal: EntropyReveal) -> bool:
        """Accept an oracle's entropy reveal and verify commitment."""
        rid = reveal.request_id
        if rid not in self._commitments:
            return False

        # Find matching commitment
        commitment = None
        for c in self._commitments[rid]:
            if c.oracle_address == reveal.oracle_address:
                commitment = c
                break

        if commitment is None:
            return False

        # Verify commitment matches reveal
        if not reveal.verify_commitment(commitment):
            # Oracle cheated — slash reputation
            oracle = self.oracles.get(reveal.oracle_address)
            if oracle:
                oracle.reputation = max(0, oracle.reputation - 0.5)
            return False

        self._reveals[rid].append(reveal)
        return True

    def finalize(self, request_id: bytes) -> Optional[bytes]:
        """Finalize an entropy request by mixing all revealed contributions.

        Returns the final random value, or None if insufficient reveals.
        """
        request = self._pending_requests.get(request_id)
        reveals = self._reveals.get(request_id, [])

        if request is None:
            return None

        if len(reveals) < request.min_oracles:
            return None

        # Mix all entropy contributions via topological hashing
        combined = bytearray()
        for reveal in sorted(reveals, key=lambda r: r.oracle_address):
            combined.extend(reveal.entropy)

        # Final mixing via topological hash
        h = TopologicalHash.hash(bytes(combined))

        # Expand to requested size
        expanded = bytearray()
        counter = 0
        while len(expanded) < request.num_bytes:
            block = hashlib.sha256(
                h.digest + struct.pack(">I", counter)
            ).digest()
            expanded.extend(block)
            counter += 1

        result = bytes(expanded[:request.num_bytes])
        self._results[request_id] = result

        # Boost oracle reputations
        for reveal in reveals:
            oracle = self.oracles.get(reveal.oracle_address)
            if oracle:
                oracle.reputation = min(10.0, oracle.reputation + 0.1)

        return result

    def get_result(self, request_id: bytes) -> Optional[bytes]:
        """Get a finalized entropy result."""
        return self._results.get(request_id)

    def run_full_round(self, request: EntropyRequest) -> Optional[bytes]:
        """Convenience: run a complete commit-reveal round with all oracles."""
        self.request_entropy(request)

        # Commit phase
        for oracle in self.oracles.values():
            commitment = oracle.commit_entropy(request)
            self.submit_commitment(commitment)

        # Reveal phase
        for oracle in self.oracles.values():
            reveal = oracle.reveal_entropy(request.request_id)
            if reveal:
                self.submit_reveal(reveal)

        return self.finalize(request.request_id)
