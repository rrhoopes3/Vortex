# $VORTEX

**SPL utility token for on-chain media provenance verification on Solana.**

$VORTEX powers a verification network that proves photos and videos are authentic, unaltered, and traceable. Provenance is bound to the content itself — not strippable metadata — and anchored on-chain.

## Token

| | |
|---|---|
| **Symbol** | $VORTEX |
| **Network** | Solana (SPL) |
| **Supply** | 48,000,000 |
| **Decimals** | 9 |
| **Mint** | `5joN44mSAdo7DbGgsKnXWagLKc8kEkFfKiTW2szTFASA` |

[View on Solscan](https://solscan.io/token/5joN44mSAdo7DbGgsKnXWagLKc8kEkFfKiTW2szTFASA) | [Trade on Jupiter](https://jup.ag/swap/SOL-5joN44mSAdo7DbGgsKnXWagLKc8kEkFfKiTW2szTFASA)

## What $VORTEX does

- **Media verification** — Verify that media hasn't been tampered with. Proofs survive compression and re-encoding.
- **On-chain anchoring** — Verification proofs are published to Solana. Immutable, public, timestamped.
- **Verification rewards** — Nodes that verify media proofs earn $VORTEX.
- **Governance** — Token holders vote on protocol upgrades.

## VRC-48M — Media Provenance

Anchor media at the point of capture. Verification that survives re-encoding but breaks under manipulation.

```bash
# Anchor a video
python -m vortexchain.vrc48m anchor video.mp4 -o anchor.json

# Verify a copy
python -m vortexchain.vrc48m verify video.mp4 anchor.json

# Compare two files
python -m vortexchain.vrc48m compare original.mp4 suspect.mp4

# Web demo
python -m vortexchain.server    # http://localhost:5000/demo
```

## Quick Start

```bash
pip install -e ".[dev]"
pytest -v
```

## Distribution

| Category | % | Amount |
|---|---|---|
| Ecosystem & Community | 30% | 14,400,000 |
| Staking Rewards | 25% | 12,000,000 |
| Team & Advisors | 15% | 7,200,000 |
| Development Fund | 15% | 7,200,000 |
| Liquidity | 10% | 4,800,000 |
| Quantum Research Grant | 5% | 2,400,000 |

## Links

- [Website](https://vortex.arc-relay.com)
- [ARC-Relay](https://arc-relay.com)
- [Solscan](https://solscan.io/token/5joN44mSAdo7DbGgsKnXWagLKc8kEkFfKiTW2szTFASA)

## License

MIT
