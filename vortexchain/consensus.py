"""Hybrid Proof-of-Stake + Proof-of-Topology consensus.

Validators must:
1. Stake $VORTEX tokens (PoS component).
2. Periodically prove they can reconstruct subsets of the topological
   spectrum (PoT component), verified via zero-knowledge proofs.
3. When quantum hardware is present, incorporate true physical randomness
   from entangled OAM photon pairs.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from vortexchain.manifold import (
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
)


# ---------------------------------------------------------------------------
# Proof of Topology
# ---------------------------------------------------------------------------

@dataclass
class TopologyChallenge:
    """A challenge issued to a validator to prove topological knowledge.

    The validator must reconstruct the wrapping numbers for a random
    subset of embedded spheres, given only the public projection.
    """
    challenge_id: bytes                  # 32-byte unique ID
    sphere_indices: Tuple[int, ...]      # which spheres to prove
    epoch: int                           # consensus epoch number

    @classmethod
    def generate(cls, epoch: int, num_spheres: int = 6) -> "TopologyChallenge":
        """Generate a random challenge for the given epoch."""
        challenge_id = os.urandom(32)

        # Deterministically select sphere indices from challenge_id
        indices: List[int] = []
        h = hashlib.sha256(challenge_id).digest()
        for i in range(num_spheres):
            idx = h[i] % NUM_EMBEDDED_SPHERES
            # Avoid duplicates
            while idx in indices:
                idx = (idx + 1) % NUM_EMBEDDED_SPHERES
            indices.append(idx)

        return cls(
            challenge_id=challenge_id,
            sphere_indices=tuple(sorted(indices)),
            epoch=epoch,
        )


@dataclass
class TopologyResponse:
    """A validator's response to a topology challenge."""
    challenge_id: bytes
    wrapping_values: Tuple[int, ...]     # values for challenged spheres
    commitment: bytes                     # ZK commitment

    @classmethod
    def create(
        cls,
        challenge: TopologyChallenge,
        manifold: TopologicalManifold,
    ) -> "TopologyResponse":
        """Create a response to a challenge using the validator's manifold."""
        spectrum = manifold.topological_spectrum()
        values = tuple(spectrum[i] for i in challenge.sphere_indices)

        # ZK commitment: hash of (challenge_id || values || random nonce)
        nonce = os.urandom(32)
        commitment_data = challenge.challenge_id
        for v in values:
            commitment_data += struct.pack(">I", v)
        commitment_data += nonce
        commitment = hashlib.sha256(commitment_data).digest()

        return cls(
            challenge_id=challenge.challenge_id,
            wrapping_values=values,
            commitment=commitment,
        )


@dataclass
class ProofOfTopology:
    """Proof-of-Topology verification engine.

    Verifies that a validator can reconstruct the correct wrapping numbers
    for randomly challenged subsets of the 48D manifold.
    """

    # Registry of validator manifold spectra (in production, only commitments
    # are stored — the full spectrum is never revealed)
    _registered_spectra: Dict[str, Tuple[int, ...]] = field(default_factory=dict)

    def register_validator(self, address: str, manifold: TopologicalManifold) -> None:
        """Register a validator's topological spectrum."""
        self._registered_spectra[address] = tuple(manifold.topological_spectrum())

    def verify_response(
        self,
        address: str,
        challenge: TopologyChallenge,
        response: TopologyResponse,
    ) -> bool:
        """Verify a validator's topology challenge response."""
        if address not in self._registered_spectra:
            return False

        if response.challenge_id != challenge.challenge_id:
            return False

        # Check that the claimed wrapping values match the registered spectrum
        spectrum = self._registered_spectra[address]
        expected = tuple(spectrum[i] for i in challenge.sphere_indices)
        return response.wrapping_values == expected


# ---------------------------------------------------------------------------
# Hybrid Consensus
# ---------------------------------------------------------------------------

@dataclass
class ValidatorState:
    """State of a validator in the hybrid consensus."""
    address: str
    stake: float
    topology_score: float = 0.0         # cumulative topology contribution
    challenges_passed: int = 0
    challenges_failed: int = 0
    has_quantum_hardware: bool = False
    manifold: Optional[TopologicalManifold] = None

    @property
    def effective_weight(self) -> float:
        """Compute effective validator weight combining stake and topology."""
        stake_weight = self.stake
        topo_weight = self.topology_score * 100  # topology is highly valued
        quantum_bonus = 1.5 if self.has_quantum_hardware else 1.0
        return (stake_weight + topo_weight) * quantum_bonus


class HybridConsensus:
    """Hybrid PoS + PoT consensus engine.

    Block proposers are selected based on a weighted combination of:
    - Staked $VORTEX tokens
    - Topological contribution score (verified invariant data)
    - Quantum hardware bonus (1.5x for nodes with OAM hardware)
    """

    def __init__(self) -> None:
        self.validators: Dict[str, ValidatorState] = {}
        self.proof_engine = ProofOfTopology()
        self.current_epoch: int = 0
        self.min_stake: float = 1000.0   # minimum stake to validate

    def register_validator(
        self,
        address: str,
        stake: float,
        manifold: TopologicalManifold,
        has_quantum: bool = False,
    ) -> bool:
        """Register a new validator."""
        if stake < self.min_stake:
            return False

        self.validators[address] = ValidatorState(
            address=address,
            stake=stake,
            has_quantum_hardware=has_quantum,
            manifold=manifold,
        )
        self.proof_engine.register_validator(address, manifold)
        return True

    def issue_challenge(self, address: str) -> Optional[TopologyChallenge]:
        """Issue a topology challenge to a validator."""
        if address not in self.validators:
            return None
        return TopologyChallenge.generate(self.current_epoch)

    def process_response(
        self,
        address: str,
        challenge: TopologyChallenge,
        response: TopologyResponse,
    ) -> bool:
        """Process a validator's challenge response."""
        if address not in self.validators:
            return False

        valid = self.proof_engine.verify_response(address, challenge, response)
        validator = self.validators[address]

        if valid:
            validator.challenges_passed += 1
            validator.topology_score += 1.0
        else:
            validator.challenges_failed += 1
            validator.topology_score = max(0, validator.topology_score - 2.0)

        return valid

    def select_proposer(self) -> Optional[str]:
        """Select the next block proposer based on weighted stake + topology.

        Uses deterministic selection weighted by effective_weight.
        """
        if not self.validators:
            return None

        total_weight = sum(v.effective_weight for v in self.validators.values())
        if total_weight <= 0:
            return None

        # Deterministic selection using epoch as seed
        h = hashlib.sha256(struct.pack(">Q", self.current_epoch)).digest()
        target = (int.from_bytes(h[:8], "big") % 10000) / 10000.0 * total_weight

        cumulative = 0.0
        for address, validator in sorted(self.validators.items()):
            cumulative += validator.effective_weight
            if cumulative >= target:
                return address

        # Fallback: return last validator
        return sorted(self.validators.keys())[-1]

    def advance_epoch(self) -> None:
        """Advance to the next consensus epoch."""
        self.current_epoch += 1
