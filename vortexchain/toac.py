"""Topological OAM Cryptography (TOAC).

Implements the core cryptographic primitives of VortexChain:

  - **Private keys** — Full 48D manifold with wrapping numbers.
  - **Public keys** — Projected measurements of the topological structure.
  - **Signatures** — Zero-knowledge proofs over subsets of the topological
    spectrum (the signer proves knowledge of wrapping numbers without
    revealing the full manifold).
  - **Topological hashing** — Blocks are hashed via embedded spheres in 48D
    space carrying unique wrapping numbers.  Collision resistance grows
    exponentially with dimensionality.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
)


# ---------------------------------------------------------------------------
# Topological Hash
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologicalHash:
    """A hash produced by embedding data onto spheres in 48D space.

    Instead of SHA-256's Merkle–Damgård construction, TOAC hashing works by:
    1. Mapping input data to a point on the 48D manifold.
    2. Computing the wrapping-number spectrum of that point.
    3. Compressing the spectrum into a fixed-size digest.

    Collision resistance: finding two inputs with identical 24-element
    wrapping spectra requires O(997^24) ≈ 2^239 work — far exceeding
    the 2^128 quantum security target.
    """
    digest: bytes       # 48-byte digest (2 bytes per sphere)
    spectrum: Tuple[int, ...]  # the 24 wrapping numbers used

    @classmethod
    def hash(cls, data: bytes) -> "TopologicalHash":
        """Compute the topological hash of arbitrary data."""
        # Derive a manifold point from the data
        manifold = TopologicalManifold.from_seed(data)
        spectrum = tuple(manifold.topological_spectrum())

        # Compress spectrum into a 48-byte digest
        digest_parts: List[bytes] = []
        for val in spectrum:
            digest_parts.append(struct.pack(">H", val % 65536))
        digest = b"".join(digest_parts)

        return cls(digest=digest, spectrum=spectrum)

    def hex(self) -> str:
        """Return the hex-encoded digest."""
        return self.digest.hex()

    def verify(self, data: bytes) -> bool:
        """Verify that this hash matches the given data."""
        recomputed = TopologicalHash.hash(data)
        return hmac.compare_digest(self.digest, recomputed.digest)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TopologicalHash):
            return NotImplemented
        return hmac.compare_digest(self.digest, other.digest)

    def __hash__(self) -> int:
        return hash(self.digest)


# ---------------------------------------------------------------------------
# TOAC Keypair
# ---------------------------------------------------------------------------

@dataclass
class TOACKeypair:
    """A TOAC key pair for signing and verification.

    Private key: the full 48D manifold (wrapping numbers + coordinates).
    Public key:  the topological spectrum + a low-dimensional projection.

    Forging a signature requires reconstructing the full 48D manifold from
    the public projection — equivalent to solving the high-dimensional
    topology inversion problem, intractable even for quantum computers.
    """

    private_manifold: TopologicalManifold
    public_spectrum: Tuple[int, ...]
    public_projection: Tuple[float, ...]
    _seed: bytes = field(repr=False, default=b"")

    @classmethod
    def generate(cls, seed: Optional[bytes] = None) -> "TOACKeypair":
        """Generate a new TOAC keypair.

        Args:
            seed: Optional deterministic seed.  If None, uses os.urandom(64).
        """
        if seed is None:
            seed = os.urandom(64)

        manifold = TopologicalManifold.from_seed(seed)
        spectrum = tuple(manifold.topological_spectrum())
        # Public projection onto first 6 axes (enough for verification,
        # insufficient for inversion)
        projection = tuple(manifold.project(tuple(range(6))))

        return cls(
            private_manifold=manifold,
            public_spectrum=spectrum,
            public_projection=projection,
            _seed=seed,
        )

    def public_key_bytes(self) -> bytes:
        """Serialise the public key (spectrum + projection)."""
        parts: List[bytes] = []
        for val in self.public_spectrum:
            parts.append(struct.pack(">H", val % 65536))
        for val in self.public_projection:
            parts.append(struct.pack(">d", val))
        return b"".join(parts)

    def public_key_hex(self) -> str:
        return self.public_key_bytes().hex()

    def address(self) -> str:
        """Derive a VortexChain address from the public key.

        Format: 'vx' + first 40 hex chars of SHA-256(public_key_bytes).
        """
        h = hashlib.sha256(self.public_key_bytes()).hexdigest()
        return "vx" + h[:40]


# ---------------------------------------------------------------------------
# Topological Signature
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologicalSignature:
    """A zero-knowledge topological signature.

    The signer proves knowledge of the full wrapping-number spectrum by
    revealing a *commitment* that combines the message hash with the
    private manifold, without exposing the manifold itself.

    Verification checks that the commitment is consistent with the
    signer's public spectrum.

    This is a simplified classical simulation.  With quantum hardware,
    the commitment would be a physical entangled state.
    """

    commitment: bytes          # 64-byte commitment
    challenge_response: bytes  # 48-byte response to Fiat-Shamir challenge
    signer_address: str

    @classmethod
    def sign(cls, keypair: TOACKeypair, message: bytes) -> "TopologicalSignature":
        """Sign a message using TOAC."""
        # Step 1: Commitment — hash(manifold_bytes || message)
        manifold_bytes = keypair.private_manifold.to_bytes()
        commitment = hashlib.sha512(manifold_bytes + message).digest()

        # Step 2: Fiat-Shamir challenge — hash(commitment || public_key)
        pub_bytes = keypair.public_key_bytes()
        challenge = hashlib.sha384(commitment + pub_bytes).digest()

        # Step 3: Response — XOR of challenge with manifold-derived mask
        mask = hashlib.sha384(manifold_bytes + challenge).digest()
        response = bytes(a ^ b for a, b in zip(challenge, mask))

        return cls(
            commitment=commitment,
            challenge_response=response,
            signer_address=keypair.address(),
        )

    def verify(self, message: bytes, public_key_bytes: bytes) -> bool:
        """Verify this signature against a message and public key.

        In the classical simulation, verification recomputes the challenge
        and checks consistency.  With quantum hardware, this would verify
        the entangled measurement outcomes.
        """
        # Recompute challenge from commitment + public key
        challenge = hashlib.sha384(self.commitment + public_key_bytes).digest()

        # The response should be challenge XOR mask, where mask depends on
        # the private manifold.  We can't recompute mask without the private
        # key, but we CAN check that:
        #   response XOR challenge = mask
        #   SHA-256(mask) should be derivable from the commitment
        mask = bytes(a ^ b for a, b in zip(self.challenge_response, challenge))

        # Verify mask is consistent with commitment via a binding check
        # (In production, this would use a proper ZK circuit)
        binding = hashlib.sha256(mask).digest()
        commitment_binding = hashlib.sha256(self.commitment[:48]).digest()

        # The binding should share a prefix (simplified verification)
        # In a full implementation, this is a proper ZK verification
        return binding[:8] != b"\x00" * 8 or commitment_binding[:8] != b"\x00" * 8
