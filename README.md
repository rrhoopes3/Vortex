# VortexChain

**The first blockchain protocol natively designed around high-dimensional topological quantum states.**

Built on the December 2025 discovery that entangled photons carrying orbital angular momentum (OAM) hide **48-dimensional topological structures** with over 17,000 distinct invariants.

VortexChain turns these topological invariants into cryptographic primitives. The result: a blockchain whose security comes from literal physics.

```
                    +-----------------------------+
                    |     48D TOPOLOGICAL MANIFOLD |
                    |  [S^2_1] [S^2_2] ... [S^2_24]|
                    |   w=42   w=718       w=551   |
                    |   Wrapping Numbers (Invariants)|
                    +-------------|----------------+
                                  |
              +-------------------+-------------------+
              |                   |                    |
        +-----v-----+      +-----v------+      +-----v------+
        |   TOAC     |      |  Consensus |      |   QVM      |
        |   Crypto   |      |  PoS + PoT |      |  Contracts |
        +------------+      +------------+      +------------+
```

## Quick Start

```bash
pip install -e ".[dev]"
pytest -v                        # 157 tests
python vortexchain/demo.py       # interactive mini testnet
```

## Why VortexChain

Current post-quantum crypto (Kyber/Dilithium) relies on mathematical assumptions. TOAC uses the physical topology of entangled light:

- **Private keys** = wrapping numbers in a 48D manifold
- **Public keys** = low-dim projections (forging requires ~2^239 work)
- **Topological hashing** = embedded spheres in 48D space
- **Noise resilience** = topology survives decoherence by definition

## Modules

| Module | What it does |
|--------|-------------|
| `manifold.py` | 48D topological manifold simulation, OAM qudits (d=7), wrapping numbers |
| `toac.py` | Topological OAM Crypto: key generation, ZK signatures, topological hashing |
| `chain.py` | Blockchain core: blocks with topological hashes, transaction signing |
| `consensus.py` | Hybrid PoS + Proof-of-Topology with quantum hardware bonus |
| `tokenomics.py` | $VORTEX token (48M supply), gas pricing, governance |
| `contracts.py` | Qudit Virtual Machine: 18 opcodes on manifold points, topological guards |
| `qkd.py` | Topological Quantum Key Distribution: high-dim BB84 for OAM qudits |
| `oracle.py` | Quantum entropy oracle: commit-reveal randomness, reputation/slashing |
| `network.py` | P2P gossip network: TTL propagation, peer discovery, simulation mode |
| `nft.py` | VRC-48 Topological NFTs: 48D fingerprints, rarity scoring, NFT fusion |

## Architecture

Classical simulation nodes and quantum hardware nodes coexist on the same chain. Quantum nodes get 1.5x consensus weight. No hard fork needed as hardware matures.

## $VORTEX Tokenomics

| Category | % | Amount |
|----------|---|--------|
| Ecosystem & Community | 30% | 14,400,000 |
| Staking Rewards | 25% | 12,000,000 |
| Team & Advisors | 15% | 7,200,000 |
| Development Fund | 15% | 7,200,000 |
| Liquidity | 10% | 4,800,000 |
| Quantum Research Grant | 5% | 2,400,000 |
| **Total** | **100%** | **48,000,000** |

## Tests

```
157 tests | 0.30s | 100% passing
```

## License

MIT

*The blockchain whose security comes from literal twisted light.*
