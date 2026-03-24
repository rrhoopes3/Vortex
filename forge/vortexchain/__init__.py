"""VortexChain: Topological OAM Cryptography Blockchain.

A crypto protocol built on the 2025 discovery of hidden 48-dimensional topology
in entangled orbital angular momentum (OAM) states of light.

Core Modules:
    manifold   - 48D topological manifold simulation via tensor networks
    toac       - Topological OAM Cryptography (keys, signatures, hashing)
    chain      - Block and blockchain structures
    consensus  - Hybrid Proof-of-Stake + Proof-of-Topology consensus
    tokenomics - $VORTEX token model and distribution

Extended Modules:
    contracts  - Qudit Smart Contract Runtime (QVM)
    qkd        - Topological Quantum Key Distribution (TopoQKD)
    oracle     - Quantum Entropy Oracle (commit-reveal randomness)
    network    - P2P gossip network and node discovery
    nft        - VRC-48 Topological NFTs with manifold fingerprints
"""

from forge.vortexchain.manifold import TopologicalManifold, WrappingNumber
from forge.vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature
from forge.vortexchain.chain import Block, Transaction, VortexChain
from forge.vortexchain.consensus import ProofOfTopology, HybridConsensus
from forge.vortexchain.tokenomics import VortexToken, TokenDistribution
from forge.vortexchain.contracts import QuditVM, QuditContract, Instruction, QuditOpcode
from forge.vortexchain.qkd import QKDSession, TopoQKDNode, EntangledOAMPair
from forge.vortexchain.oracle import EntropyAggregator, OracleNode, EntropyRequest
from forge.vortexchain.network import VortexNode, VortexNetwork, MessageType
from forge.vortexchain.nft import TopoNFT, TopoNFTCollection, TopologicalFingerprint, fuse_nfts

__all__ = [
    # Core
    "TopologicalManifold",
    "WrappingNumber",
    "TOACKeypair",
    "TopologicalHash",
    "TopologicalSignature",
    "Block",
    "Transaction",
    "VortexChain",
    "ProofOfTopology",
    "HybridConsensus",
    "VortexToken",
    "TokenDistribution",
    # Extended
    "QuditVM",
    "QuditContract",
    "Instruction",
    "QuditOpcode",
    "QKDSession",
    "TopoQKDNode",
    "EntangledOAMPair",
    "EntropyAggregator",
    "OracleNode",
    "EntropyRequest",
    "VortexNode",
    "VortexNetwork",
    "MessageType",
    "TopoNFT",
    "TopoNFTCollection",
    "TopologicalFingerprint",
    "fuse_nfts",
]
