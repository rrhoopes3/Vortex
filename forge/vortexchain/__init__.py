"""VortexChain: Topological OAM Cryptography Blockchain.

A crypto protocol built on the 2025 discovery of hidden 48-dimensional topology
in entangled orbital angular momentum (OAM) states of light.

Modules:
    manifold   - 48D topological manifold simulation via tensor networks
    toac       - Topological OAM Cryptography (keys, signatures, hashing)
    chain      - Block and blockchain structures
    consensus  - Hybrid Proof-of-Stake + Proof-of-Topology consensus
    tokenomics - $VORTEX token model and distribution
"""

from forge.vortexchain.manifold import TopologicalManifold, WrappingNumber
from forge.vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature
from forge.vortexchain.chain import Block, VortexChain
from forge.vortexchain.consensus import ProofOfTopology, HybridConsensus
from forge.vortexchain.tokenomics import VortexToken, TokenDistribution

__all__ = [
    "TopologicalManifold",
    "WrappingNumber",
    "TOACKeypair",
    "TopologicalHash",
    "TopologicalSignature",
    "Block",
    "VortexChain",
    "ProofOfTopology",
    "HybridConsensus",
    "VortexToken",
    "TokenDistribution",
]
