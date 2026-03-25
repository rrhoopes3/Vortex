"""VortexChain Dev Server.

Flask API + dashboard for interacting with VortexChain.
Run with: python -m forge.vortexchain.server
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename

from forge.vortexchain import (
    VortexChain,
    Transaction,
    TOACKeypair,
    TopologicalManifold,
    TopoNFT,
    TopoNFTCollection,
    fuse_nfts,
    VortexNode,
    VortexNetwork,
    MessageType,
    TopoQKDNode,
    EntropyAggregator,
    OracleNode,
    EntropyRequest,
    TokenDistribution,
    VortexToken,
    QuditVM,
    QuditContract,
    Instruction,
    QuditOpcode,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# State — all in-memory for the dev server
# ---------------------------------------------------------------------------

chain = VortexChain()
wallets: dict[str, TOACKeypair] = {}
nft_collection = TopoNFTCollection(name="VortexGenesis", symbol="VXNFT")
token = VortexToken()
network = VortexNetwork()
qkd_nodes: dict[str, TopoQKDNode] = {}


def _seed_state():
    """Pre-populate the chain with validators, wallets, and sample NFTs."""
    names = ["alice", "bob", "charlie"]
    for name in names:
        kp = TOACKeypair.generate(seed=name.encode() * 8)
        wallets[name] = kp
        chain.register_validator(kp.address(), 1000.0)

        # Network nodes
        node = VortexNode(
            node_id=name,
            vx_address=kp.address(),
            is_validator=True,
            has_quantum=(name == "alice"),
        )
        network.add_node(node)

        # QKD nodes
        qkd_nodes[name] = TopoQKDNode(node_id=name)

    # Mine a couple of seed blocks
    tx = Transaction(
        sender=wallets["alice"].address(),
        recipient=wallets["bob"].address(),
        amount=100.0,
    )
    tx.sign(wallets["alice"])
    chain.add_transaction(tx)
    chain.create_block(validator=wallets["alice"].address())

    # Mint sample NFTs
    for name in names:
        nft_collection.mint(
            creator=wallets[name].address(),
            metadata={"name": f"{name.title()}'s Genesis Vortex"},
        )


_seed_state()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


def ok(data):
    return jsonify({"ok": True, "data": data})


def err(msg, status=400):
    return jsonify({"ok": False, "error": msg}), status


# ---------------------------------------------------------------------------
# Routes — Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file(DASHBOARD_PATH)


# ---------------------------------------------------------------------------
# Routes — Chain
# ---------------------------------------------------------------------------

@app.route("/api/chain")
def get_chain():
    return ok({
        "height": chain.height,
        "valid": chain.validate_chain(),
        "validators": {addr: stake for addr, stake in chain.validators.items()},
        "pending_tx": len(chain.pending_transactions),
        "blocks": [
            {
                "index": b.index,
                "hash": b.block_hash[:24] + "...",
                "validator": b.validator,
                "tx_count": len(b.transactions),
                "timestamp": b.timestamp,
            }
            for b in chain.chain[-10:]  # last 10 blocks
        ],
    })


@app.route("/api/chain/block", methods=["POST"])
def mine_block():
    body = request.get_json(silent=True) or {}
    validator_name = body.get("validator", "alice")
    if validator_name not in wallets:
        return err(f"Unknown validator: {validator_name}")
    kp = wallets[validator_name]
    block = chain.create_block(validator=kp.address())
    return ok({
        "index": block.index,
        "hash": block.block_hash,
        "validator": block.validator,
        "tx_count": len(block.transactions),
    })


# ---------------------------------------------------------------------------
# Routes — Wallet
# ---------------------------------------------------------------------------

@app.route("/api/wallet/new", methods=["POST"])
def new_wallet():
    kp = TOACKeypair.generate()
    name = f"wallet_{len(wallets)}"
    wallets[name] = kp
    return ok({
        "name": name,
        "address": kp.address(),
        "public_key": kp.public_key_hex()[:32] + "...",
    })


@app.route("/api/wallets")
def list_wallets():
    return ok({
        name: {"address": kp.address()}
        for name, kp in wallets.items()
    })


# ---------------------------------------------------------------------------
# Routes — Transactions
# ---------------------------------------------------------------------------

@app.route("/api/tx", methods=["POST"])
def submit_tx():
    body = request.get_json(silent=True) or {}
    sender_name = body.get("sender", "alice")
    recipient_name = body.get("recipient", "bob")
    amount = float(body.get("amount", 1.0))

    if sender_name not in wallets:
        return err(f"Unknown sender: {sender_name}")
    if recipient_name not in wallets:
        return err(f"Unknown recipient: {recipient_name}")

    tx = Transaction(
        sender=wallets[sender_name].address(),
        recipient=wallets[recipient_name].address(),
        amount=amount,
    )
    tx.sign(wallets[sender_name])
    tx_hash = chain.add_transaction(tx)
    return ok({
        "tx_hash": tx_hash.hex(),
        "sender": sender_name,
        "recipient": recipient_name,
        "amount": amount,
        "pending_count": len(chain.pending_transactions),
    })


# ---------------------------------------------------------------------------
# Routes — NFTs
# ---------------------------------------------------------------------------

@app.route("/api/nft/collection")
def get_nft_collection():
    stats = nft_collection.collection_stats()
    tokens = []
    for nft in nft_collection._tokens.values():
        tokens.append({
            "token_id": nft.token_id,
            "owner": nft.owner[:16] + "...",
            "rarity": round(nft.rarity_score, 4),
            "state": nft.state.name,
            "metadata": nft.metadata,
        })
    return ok({"stats": stats, "tokens": tokens})


@app.route("/api/nft/mint", methods=["POST"])
def mint_nft():
    body = request.get_json(silent=True) or {}
    creator_name = body.get("creator", "alice")
    name = body.get("name", "Unnamed Vortex")

    if creator_name not in wallets:
        return err(f"Unknown creator: {creator_name}")

    nft = nft_collection.mint(
        creator=wallets[creator_name].address(),
        metadata={"name": name},
    )
    return ok({
        "token_id": nft.token_id,
        "rarity": round(nft.rarity_score, 4),
        "fingerprint_spectrum": list(nft.fingerprint.spectrum[:6]),
        "creator": creator_name,
    })


@app.route("/api/nft/fuse", methods=["POST"])
def fuse_nft():
    body = request.get_json(silent=True) or {}
    token_a = body.get("token_a")
    token_b = body.get("token_b")
    owner_name = body.get("owner", "alice")

    if not token_a or not token_b:
        return err("Provide token_a and token_b IDs")
    if owner_name not in wallets:
        return err(f"Unknown owner: {owner_name}")

    child = nft_collection.fuse(token_a, token_b, wallets[owner_name].address())
    if child is None:
        return err("Fusion failed — check token IDs and ownership")
    return ok({
        "child_token_id": child.token_id,
        "child_rarity": round(child.rarity_score, 4),
        "parent_a": token_a,
        "parent_b": token_b,
    })


# ---------------------------------------------------------------------------
# Routes — QKD
# ---------------------------------------------------------------------------

@app.route("/api/qkd/handshake", methods=["POST"])
def qkd_handshake():
    body = request.get_json(silent=True) or {}
    alice_name = body.get("alice", "alice")
    bob_name = body.get("bob", "bob")
    num_pairs = int(body.get("num_pairs", 500))

    if alice_name not in qkd_nodes or bob_name not in qkd_nodes:
        return err("Unknown QKD node names")

    alice_node = qkd_nodes[alice_name]
    key = alice_node.establish_key(bob_name, num_pairs=num_pairs)
    if key is None:
        return err("QKD handshake failed — key distillation unsuccessful")
    return ok({
        "alice": alice_name,
        "bob": bob_name,
        "shared_key_hex": key.hex()[:32] + "...",
        "key_length_bytes": len(key),
        "num_pairs_used": num_pairs,
    })


# ---------------------------------------------------------------------------
# Routes — Oracle
# ---------------------------------------------------------------------------

@app.route("/api/oracle/entropy", methods=["POST"])
def oracle_entropy():
    body = request.get_json(silent=True) or {}
    num_bytes = int(body.get("num_bytes", 32))

    aggregator = EntropyAggregator()
    for name, kp in list(wallets.items())[:3]:
        oracle = OracleNode(address=kp.address(), stake=100.0)
        aggregator.register_oracle(oracle)

    req = EntropyRequest.create(
        requester=wallets["alice"].address(),
        num_bytes=num_bytes,
        min_oracles=3,
    )
    result = aggregator.run_full_round(req)
    if result is None:
        return err("Entropy generation failed")
    return ok({
        "entropy_hex": result.hex(),
        "length_bytes": len(result),
        "oracle_count": 3,
        "method": "commit-reveal + topological mixing",
    })


# ---------------------------------------------------------------------------
# Routes — Network
# ---------------------------------------------------------------------------

@app.route("/api/network/status")
def network_status():
    stats = network.network_stats()
    return ok(stats)


# ---------------------------------------------------------------------------
# Routes — Tokenomics
# ---------------------------------------------------------------------------

@app.route("/api/tokenomics")
def tokenomics():
    dist = TokenDistribution()
    return ok({
        "ticker": "VORTEX",
        "total_supply": 48_000_000,
        "summary": dist.summary(),
        "gas_example": {
            "1_qudit_dim": token.calculate_gas(qudit_dimensions=1),
            "7_qudit_dim": token.calculate_gas(qudit_dimensions=7),
            "48_qudit_dim": token.calculate_gas(qudit_dimensions=48),
        },
    })


# ---------------------------------------------------------------------------
# Routes — VRC-48M Media Provenance
# ---------------------------------------------------------------------------

UPLOAD_DIR = Path(tempfile.gettempdir()) / "vrc48m_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ANCHOR_DIR = Path(tempfile.gettempdir()) / "vrc48m_anchors"
ANCHOR_DIR.mkdir(exist_ok=True)

# Store anchors in memory for quick access
media_anchors: dict[str, dict] = {}


@app.route("/vrc48m")
def vrc48m_ui():
    return send_file(Path(__file__).parent / "vrc48m_ui.html")


@app.route("/api/vrc48m/anchor", methods=["POST"])
def vrc48m_anchor():
    """Upload media and create a topological anchor."""
    from forge.vortexchain.vrc48m import (
        analyze_video, analyze_image, MediaAnchor,
    )

    if "file" not in request.files:
        return err("No file uploaded")

    f = request.files["file"]
    if not f.filename:
        return err("Empty filename")

    filename = secure_filename(f.filename)
    filepath = UPLOAD_DIR / filename
    f.save(str(filepath))

    try:
        ext = filepath.suffix.lower()
        if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'):
            analysis = analyze_image(str(filepath))
        else:
            analysis = analyze_video(str(filepath))

        anchor = MediaAnchor.from_analysis(analysis)
        anchor_id = f"vrc48m_{int(time.time())}_{filename}"

        # Save anchor
        anchor_path = ANCHOR_DIR / f"{anchor_id}.json"
        anchor.save(str(anchor_path))

        # Store in memory
        media_anchors[anchor_id] = {
            "anchor": anchor,
            "filepath": str(filepath),
            "created": time.time(),
        }

        return ok({
            "anchor_id": anchor_id,
            "filename": filename,
            "frame_count": anchor.frame_count,
            "duration_ms": anchor.duration_ms,
            "resolution": f"{anchor.width}x{anchor.height}",
            "chunks": len(anchor.chunk_spectra),
            "merkle_root": anchor.video_merkle_root[:32] + "...",
            "processing_time_ms": round(anchor.processing_time_ms, 1),
            "sample_spectra": anchor.sample_spectra,
        })
    except Exception as e:
        return err(f"Analysis failed: {str(e)}")


@app.route("/api/vrc48m/verify", methods=["POST"])
def vrc48m_verify():
    """Verify uploaded media against an anchor."""
    from forge.vortexchain.vrc48m import (
        verify_media, quick_verify, MediaAnchor,
    )

    if "file" not in request.files:
        return err("No file uploaded")
    anchor_id = request.form.get("anchor_id", "")
    quick = request.form.get("quick", "false") == "true"

    if anchor_id not in media_anchors:
        return err(f"Unknown anchor: {anchor_id}")

    f = request.files["file"]
    filename = secure_filename(f.filename or "verify_file")
    filepath = UPLOAD_DIR / f"verify_{filename}"
    f.save(str(filepath))

    try:
        anchor = media_anchors[anchor_id]["anchor"]

        if quick:
            result = quick_verify(str(filepath), anchor)
        else:
            result = verify_media(str(filepath), anchor)

        tampered_list = []
        for tc in result.tampered_chunks:
            tampered_list.append({
                "chunk_index": tc.chunk_index,
                "frame_start": tc.frame_start,
                "frame_end": tc.frame_end,
                "time_start_s": round(tc.time_start_ms / 1000, 2),
                "time_end_s": round(tc.time_end_ms / 1000, 2),
                "spectral_distance": tc.spectral_distance,
                "classification": tc.classification,
            })

        return ok({
            "status": result.status.value,
            "confidence": round(result.confidence, 4),
            "merkle_match": result.merkle_match,
            "total_chunks": result.total_chunks,
            "matching_chunks": result.matching_chunks,
            "tampered_chunks": tampered_list,
            "processing_time_ms": round(result.processing_time_ms, 1),
        })
    except Exception as e:
        return err(f"Verification failed: {str(e)}")


@app.route("/api/vrc48m/compare", methods=["POST"])
def vrc48m_compare():
    """Compare two uploaded media files."""
    from forge.vortexchain.vrc48m import compare_media

    if "original" not in request.files or "suspect" not in request.files:
        return err("Need both 'original' and 'suspect' files")

    orig = request.files["original"]
    susp = request.files["suspect"]
    orig_name = secure_filename(orig.filename or "original")
    susp_name = secure_filename(susp.filename or "suspect")

    orig_path = UPLOAD_DIR / f"cmp_orig_{orig_name}"
    susp_path = UPLOAD_DIR / f"cmp_susp_{susp_name}"
    orig.save(str(orig_path))
    susp.save(str(susp_path))

    try:
        result = compare_media(str(orig_path), str(susp_path))

        tampered_list = []
        for tc in result.tampered_chunks:
            tampered_list.append({
                "chunk_index": tc.chunk_index,
                "time_start_s": round(tc.time_start_ms / 1000, 2),
                "time_end_s": round(tc.time_end_ms / 1000, 2),
                "spectral_distance": tc.spectral_distance,
                "classification": tc.classification,
            })

        return ok({
            "status": result.status.value,
            "confidence": round(result.confidence, 4),
            "total_chunks": result.total_chunks,
            "matching_chunks": result.matching_chunks,
            "tampered_chunks": tampered_list,
            "processing_time_ms": round(result.processing_time_ms, 1),
        })
    except Exception as e:
        return err(f"Comparison failed: {str(e)}")


@app.route("/api/vrc48m/anchors")
def vrc48m_list_anchors():
    """List all stored anchors."""
    anchors = []
    for aid, info in media_anchors.items():
        a = info["anchor"]
        anchors.append({
            "anchor_id": aid,
            "filename": Path(a.file_path).name,
            "frame_count": a.frame_count,
            "duration_ms": a.duration_ms,
            "chunks": len(a.chunk_spectra),
            "merkle_root": a.video_merkle_root[:32] + "...",
            "created": info["created"],
        })
    return ok(anchors)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n  +----------------------------------------------+")
    print("  |       VortexChain Dev Server v0.1.0          |")
    print("  |   Topological OAM Cryptography Protocol      |")
    print("  +----------------------------------------------+")
    print("  |  Dashboard:  http://localhost:5000            |")
    print("  |  API:        http://localhost:5000/api/chain  |")
    print("  +----------------------------------------------+\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
