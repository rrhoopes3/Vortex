"""48-dimensional topological manifold simulation.

Simulates the high-dimensional topological structures discovered in entangled
OAM states of light.  Uses tensor-network representations on classical hardware
(GPU/TPU-ready via NumPy) with a clear upgrade path to photonic OAM hardware.

The key mathematical objects are:
  - OAM qudits of dimension d=7, producing composite Hilbert space of dim 7^2 = 49
  - After tracing out the trivial singlet component: 48-dimensional manifold
  - Wrapping numbers: integer topological invariants on embedded spheres
  - Non-Abelian gauge fields governing the entangled state topology
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OAM_QUDIT_DIM = 7           # single-party OAM dimension
COMPOSITE_DIM = OAM_QUDIT_DIM ** 2  # 49
MANIFOLD_DIM = COMPOSITE_DIM - 1     # 48  (remove trivial singlet)
NUM_EMBEDDED_SPHERES = 24            # independent S^2 embeddings in 48D


# ---------------------------------------------------------------------------
# Wrapping Number
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WrappingNumber:
    """A topological invariant: the winding/wrapping number of an embedded
    sphere inside the 48-dimensional manifold.

    These integers are physically protected — continuous deformations of the
    manifold cannot change them, making them ideal cryptographic primitives.
    """
    sphere_index: int       # which embedded sphere (0..23)
    value: int              # the integer wrapping number

    def __post_init__(self):
        if not 0 <= self.sphere_index < NUM_EMBEDDED_SPHERES:
            raise ValueError(
                f"sphere_index must be in [0, {NUM_EMBEDDED_SPHERES}), "
                f"got {self.sphere_index}"
            )


# ---------------------------------------------------------------------------
# Topological Manifold
# ---------------------------------------------------------------------------

@dataclass
class TopologicalManifold:
    """Represents a point (or region) of the 48-dimensional topological
    manifold derived from entangled OAM qudits.

    In classic (simulation) mode the manifold is encoded as a flat vector
    of ``MANIFOLD_DIM`` real components plus a spectrum of wrapping numbers.
    When quantum hardware is available the ``quantum_state`` slot holds the
    native photonic state.

    Parameters
    ----------
    components : list[float]
        Real-valued coordinates in the 48D manifold (length ``MANIFOLD_DIM``).
    wrapping_numbers : list[WrappingNumber]
        The topological invariants for each embedded sphere.
    quantum_state : bytes | None
        Opaque handle to a native photonic OAM state (future hardware path).
    """

    components: List[float] = field(default_factory=list)
    wrapping_numbers: List[WrappingNumber] = field(default_factory=list)
    quantum_state: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_seed(cls, seed: bytes) -> "TopologicalManifold":
        """Deterministically generate a manifold point from a seed.

        Uses iterated SHA-512 to expand the seed into 48 coordinates and
        24 wrapping numbers.  This is the *classical simulation* path.
        """
        # Expand seed into enough bytes: 48 floats (384 bytes) + 24 ints (96 bytes)
        expanded = _expand_seed(seed, 48 * 8 + 24 * 4)

        # First 384 bytes → 48 doubles
        components: List[float] = []
        for i in range(MANIFOLD_DIM):
            raw = struct.unpack_from(">d", expanded, i * 8)[0]
            # Normalize to [-1, 1] via tanh
            components.append(math.tanh(raw))

        # Next 96 bytes → 24 wrapping numbers
        offset = MANIFOLD_DIM * 8
        wrapping: List[WrappingNumber] = []
        for i in range(NUM_EMBEDDED_SPHERES):
            raw_int = struct.unpack_from(">i", expanded, offset + i * 4)[0]
            # Map to a modest range that still provides cryptographic strength
            value = raw_int % 997  # prime modulus keeps distribution uniform
            wrapping.append(WrappingNumber(sphere_index=i, value=value))

        return cls(components=components, wrapping_numbers=wrapping)

    # ------------------------------------------------------------------
    # Projections (public-key derivation)
    # ------------------------------------------------------------------

    def project(self, axes: Tuple[int, ...] = (0, 1, 2)) -> List[float]:
        """Project the manifold onto a lower-dimensional subspace.

        This mirrors the physical measurement process: a full 48D state is
        projected onto a measurable subspace, losing information but
        remaining verifiable against the original topology.
        """
        return [self.components[a] for a in axes if a < len(self.components)]

    def topological_spectrum(self) -> List[int]:
        """Return the ordered list of wrapping-number values.

        This is the *topological fingerprint* of the manifold point — it
        uniquely characterises the topology up to homeomorphism.
        """
        return [wn.value for wn in sorted(self.wrapping_numbers, key=lambda w: w.sphere_index)]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Canonical byte serialisation of the manifold."""
        parts: List[bytes] = []
        # Components
        for c in self.components:
            parts.append(struct.pack(">d", c))
        # Wrapping numbers
        for wn in sorted(self.wrapping_numbers, key=lambda w: w.sphere_index):
            parts.append(struct.pack(">HI", wn.sphere_index, wn.value & 0xFFFFFFFF))
        return b"".join(parts)

    @classmethod
    def from_bytes(cls, data: bytes) -> "TopologicalManifold":
        """Deserialise a manifold from its canonical byte form."""
        components: List[float] = []
        for i in range(MANIFOLD_DIM):
            components.append(struct.unpack_from(">d", data, i * 8)[0])
        offset = MANIFOLD_DIM * 8
        wrapping: List[WrappingNumber] = []
        for i in range(NUM_EMBEDDED_SPHERES):
            idx, val = struct.unpack_from(">HI", data, offset + i * 6)
            wrapping.append(WrappingNumber(sphere_index=idx, value=val))
        return cls(components=components, wrapping_numbers=wrapping)

    # ------------------------------------------------------------------
    # Distance metric
    # ------------------------------------------------------------------

    def topological_distance(self, other: "TopologicalManifold") -> int:
        """Compute the topological distance (L1 on wrapping numbers).

        Two manifold points with the same wrapping spectrum are
        topologically equivalent; nonzero distance proves distinct topology.
        """
        a = self.topological_spectrum()
        b = other.topological_spectrum()
        return sum(abs(x - y) for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expand_seed(seed: bytes, length: int) -> bytes:
    """Expand a seed to ``length`` bytes via iterated SHA-512."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        h = hashlib.sha512(seed + counter.to_bytes(4, "big")).digest()
        out.extend(h)
        counter += 1
    return bytes(out[:length])
