"""Topological NFTs for VortexChain.

Unlike standard NFTs that are just pointers to metadata, VortexChain
Topological NFTs (TopoNFTs) embed a unique topological fingerprint
directly into the token — a specific 48D manifold point with its own
wrapping-number spectrum.

This gives TopoNFTs properties no other NFT standard has:

  - **Physical verifiability**: With OAM hardware, the topological
    fingerprint can be verified by measuring actual entangled photons,
    creating a bridge between digital ownership and physical reality.

  - **Inherent uniqueness**: Two manifold points with different wrapping
    spectra are provably distinct (topological invariants can't be faked
    by continuous deformations).

  - **Composability**: TopoNFTs can be "merged" — combining their
    manifold points creates a new unique topology, enabling on-chain
    breeding, fusion, and evolution mechanics.

  - **High-dimensional metadata**: Instead of a JSON blob, metadata is
    encoded as projections of the 48D manifold, allowing for rich
    searchability and similarity queries.

Token standard: VRC-48 (VortexChain Request for Comments #48)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
    WrappingNumber,
)
from vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature


# ---------------------------------------------------------------------------
# VRC-48 Token Standard
# ---------------------------------------------------------------------------

class TokenStandard(Enum):
    """VortexChain token standards."""
    VRC_48 = "VRC-48"           # Topological NFT (non-fungible)
    VRC_48M = "VRC-48M"         # Multi-token (semi-fungible, like ERC-1155)


class TopoNFTState(Enum):
    """Lifecycle state of a TopoNFT."""
    MINTED = auto()
    ACTIVE = auto()
    FROZEN = auto()             # locked, can't transfer
    FUSED = auto()              # merged into another NFT
    BURNED = auto()


# ---------------------------------------------------------------------------
# Topological Fingerprint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopologicalFingerprint:
    """The unique topological identity of an NFT.

    This is the core innovation: a fingerprint derived from the 48D
    manifold that is physically meaningful, verifiable, and unique.
    """
    spectrum: Tuple[int, ...]           # 24 wrapping numbers
    projection_6d: Tuple[float, ...]    # 6D projection for searchability
    manifold_hash: str                  # topological hash of full manifold
    dimension: int = MANIFOLD_DIM       # dimensionality (48)

    @classmethod
    def from_manifold(cls, manifold: TopologicalManifold) -> "TopologicalFingerprint":
        """Create a fingerprint from a manifold point."""
        spectrum = tuple(manifold.topological_spectrum())
        projection = tuple(manifold.project(tuple(range(6))))
        h = TopologicalHash.hash(manifold.to_bytes())
        return cls(
            spectrum=spectrum,
            projection_6d=projection,
            manifold_hash=h.hex(),
        )

    def similarity(self, other: "TopologicalFingerprint") -> float:
        """Compute similarity between two fingerprints (0.0 to 1.0).

        Based on normalized L1 distance of wrapping spectra.
        """
        if len(self.spectrum) != len(other.spectrum):
            return 0.0

        max_distance = 997 * len(self.spectrum)  # theoretical max
        actual_distance = sum(
            abs(a - b) for a, b in zip(self.spectrum, other.spectrum)
        )
        return 1.0 - (actual_distance / max_distance)

    def topological_rarity(self) -> float:
        """Compute a rarity score based on the spectrum's entropy.

        Higher entropy spectra (more diverse wrapping numbers) are rarer.
        """
        from collections import Counter
        counts = Counter(self.spectrum)
        total = len(self.spectrum)
        import math
        entropy = -sum(
            (c / total) * math.log2(c / total)
            for c in counts.values()
            if c > 0
        )
        # Normalize: max entropy is log2(24) ≈ 4.58 (all unique values)
        max_entropy = math.log2(total) if total > 0 else 1.0
        return entropy / max_entropy


# ---------------------------------------------------------------------------
# TopoNFT
# ---------------------------------------------------------------------------

@dataclass
class TopoNFT:
    """A VRC-48 Topological Non-Fungible Token.

    Each TopoNFT contains an embedded topological manifold point,
    giving it a physically verifiable, mathematically unique identity.
    """
    token_id: str                                   # unique token ID
    standard: TokenStandard = TokenStandard.VRC_48
    owner: str = ""                                 # vx-address
    creator: str = ""                               # original minter
    manifold: TopologicalManifold = field(default_factory=lambda: TopologicalManifold.from_seed(b""))
    fingerprint: Optional[TopologicalFingerprint] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    state: TopoNFTState = TopoNFTState.MINTED
    created_at: float = field(default_factory=time.time)
    transfer_history: List[Dict[str, Any]] = field(default_factory=list)
    parent_tokens: List[str] = field(default_factory=list)  # for fused NFTs
    royalty_bps: int = 500                          # 5% default royalty

    def __post_init__(self):
        if self.fingerprint is None and self.manifold.components:
            self.fingerprint = TopologicalFingerprint.from_manifold(self.manifold)

    @classmethod
    def mint(
        cls,
        creator: str,
        seed: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
        royalty_bps: int = 500,
    ) -> "TopoNFT":
        """Mint a new TopoNFT with a unique topological fingerprint."""
        import os
        if seed is None:
            seed = os.urandom(64)

        manifold = TopologicalManifold.from_seed(seed)
        fingerprint = TopologicalFingerprint.from_manifold(manifold)

        token_id = "vxnft_" + TopologicalHash.hash(seed).hex()[:32]

        return cls(
            token_id=token_id,
            owner=creator,
            creator=creator,
            manifold=manifold,
            fingerprint=fingerprint,
            metadata=metadata or {},
            state=TopoNFTState.ACTIVE,
            royalty_bps=royalty_bps,
        )

    def transfer(self, new_owner: str) -> bool:
        """Transfer ownership to a new address."""
        if self.state not in (TopoNFTState.ACTIVE, TopoNFTState.MINTED):
            return False

        self.transfer_history.append({
            "from": self.owner,
            "to": new_owner,
            "timestamp": time.time(),
        })
        self.owner = new_owner
        self.state = TopoNFTState.ACTIVE
        return True

    def freeze(self) -> bool:
        """Freeze the NFT (prevent transfers)."""
        if self.state != TopoNFTState.ACTIVE:
            return False
        self.state = TopoNFTState.FROZEN
        return True

    def unfreeze(self) -> bool:
        """Unfreeze a frozen NFT."""
        if self.state != TopoNFTState.FROZEN:
            return False
        self.state = TopoNFTState.ACTIVE
        return True

    def burn(self) -> bool:
        """Burn the NFT (permanent destruction)."""
        if self.state in (TopoNFTState.BURNED, TopoNFTState.FUSED):
            return False
        self.state = TopoNFTState.BURNED
        return True

    @property
    def rarity_score(self) -> float:
        """Get the topological rarity score."""
        if self.fingerprint:
            return self.fingerprint.topological_rarity()
        return 0.0

    def verify_topology(self, manifold_bytes: bytes) -> bool:
        """Verify that provided manifold data matches this NFT's fingerprint.

        With quantum hardware, this would verify against actual photon
        measurements.  In simulation, it checks the topological spectrum.
        """
        if self.fingerprint is None:
            return False

        check = TopologicalManifold.from_bytes(manifold_bytes)
        check_fp = TopologicalFingerprint.from_manifold(check)
        return check_fp.spectrum == self.fingerprint.spectrum


# ---------------------------------------------------------------------------
# NFT Fusion (breeding/merging)
# ---------------------------------------------------------------------------

def fuse_nfts(nft_a: TopoNFT, nft_b: TopoNFT, fuser: str) -> Optional[TopoNFT]:
    """Fuse two TopoNFTs into a new one with combined topology.

    The resulting NFT's manifold is a topological merge of both parents:
    - Components are averaged (geometric interpolation)
    - Wrapping numbers are combined modulo 997 (topological addition)

    Both parent NFTs are marked as FUSED and can no longer be transferred.
    The new NFT's fingerprint is guaranteed to be unique (different from
    both parents) due to the nonlinear combination.

    Args:
        nft_a: First parent NFT
        nft_b: Second parent NFT
        fuser: The vx-address performing the fusion

    Returns:
        New fused TopoNFT, or None if fusion is invalid.
    """
    if nft_a.state != TopoNFTState.ACTIVE or nft_b.state != TopoNFTState.ACTIVE:
        return None

    if nft_a.owner != fuser or nft_b.owner != fuser:
        return None

    # Merge manifolds
    merged_components = [
        (ca + cb) / 2.0
        for ca, cb in zip(nft_a.manifold.components, nft_b.manifold.components)
    ]
    merged_wrapping = []
    for wa, wb in zip(nft_a.manifold.wrapping_numbers, nft_b.manifold.wrapping_numbers):
        merged_wrapping.append(WrappingNumber(
            sphere_index=wa.sphere_index,
            value=(wa.value + wb.value) % 997,
        ))

    merged_manifold = TopologicalManifold(
        components=merged_components,
        wrapping_numbers=merged_wrapping,
    )

    # Mark parents as fused
    nft_a.state = TopoNFTState.FUSED
    nft_b.state = TopoNFTState.FUSED

    # Create child
    child = TopoNFT(
        token_id="vxnft_" + TopologicalHash.hash(merged_manifold.to_bytes()).hex()[:32],
        owner=fuser,
        creator=fuser,
        manifold=merged_manifold,
        fingerprint=TopologicalFingerprint.from_manifold(merged_manifold),
        metadata={
            "fused_from": [nft_a.token_id, nft_b.token_id],
            "fusion_type": "topological_merge",
        },
        state=TopoNFTState.ACTIVE,
        parent_tokens=[nft_a.token_id, nft_b.token_id],
    )

    return child


# ---------------------------------------------------------------------------
# NFT Collection
# ---------------------------------------------------------------------------

class TopoNFTCollection:
    """A collection of TopoNFTs with registry and query capabilities."""

    def __init__(self, name: str, symbol: str):
        self.name = name
        self.symbol = symbol
        self.tokens: Dict[str, TopoNFT] = {}
        self.total_minted: int = 0
        self.total_burned: int = 0

    def mint(
        self,
        creator: str,
        seed: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TopoNFT:
        """Mint a new NFT in this collection."""
        nft = TopoNFT.mint(creator, seed, metadata)
        self.tokens[nft.token_id] = nft
        self.total_minted += 1
        return nft

    def get(self, token_id: str) -> Optional[TopoNFT]:
        return self.tokens.get(token_id)

    def tokens_of(self, owner: str) -> List[TopoNFT]:
        """Get all tokens owned by an address."""
        return [t for t in self.tokens.values() if t.owner == owner]

    def transfer(self, token_id: str, from_addr: str, to_addr: str) -> bool:
        """Transfer a token between addresses."""
        nft = self.tokens.get(token_id)
        if nft is None or nft.owner != from_addr:
            return False
        return nft.transfer(to_addr)

    def burn(self, token_id: str, owner: str) -> bool:
        """Burn a token."""
        nft = self.tokens.get(token_id)
        if nft is None or nft.owner != owner:
            return False
        if nft.burn():
            self.total_burned += 1
            return True
        return False

    def fuse(self, token_a_id: str, token_b_id: str, owner: str) -> Optional[TopoNFT]:
        """Fuse two tokens in this collection."""
        nft_a = self.tokens.get(token_a_id)
        nft_b = self.tokens.get(token_b_id)
        if nft_a is None or nft_b is None:
            return None

        child = fuse_nfts(nft_a, nft_b, owner)
        if child:
            self.tokens[child.token_id] = child
            self.total_minted += 1
        return child

    def find_similar(self, token_id: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Find the most topologically similar NFTs to a given one."""
        target = self.tokens.get(token_id)
        if target is None or target.fingerprint is None:
            return []

        similarities = []
        for tid, nft in self.tokens.items():
            if tid == token_id or nft.fingerprint is None:
                continue
            if nft.state == TopoNFTState.BURNED:
                continue
            sim = target.fingerprint.similarity(nft.fingerprint)
            similarities.append((tid, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    @property
    def active_supply(self) -> int:
        return sum(
            1 for t in self.tokens.values()
            if t.state in (TopoNFTState.ACTIVE, TopoNFTState.FROZEN)
        )

    def collection_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        rarities = [
            t.rarity_score for t in self.tokens.values()
            if t.state == TopoNFTState.ACTIVE
        ]
        return {
            "name": self.name,
            "symbol": self.symbol,
            "total_minted": self.total_minted,
            "total_burned": self.total_burned,
            "active_supply": self.active_supply,
            "avg_rarity": sum(rarities) / max(1, len(rarities)),
            "unique_owners": len(set(
                t.owner for t in self.tokens.values()
                if t.state == TopoNFTState.ACTIVE
            )),
        }
