"""VortexChain Dev Server.

Flask API + dashboard for interacting with VortexChain.
Run with: python -m vortexchain.server
"""

from __future__ import annotations

import logging
import os
import struct
import tempfile
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file, Response
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from vortexchain.streaming_sessions import (
    SessionConfig,
    SessionManager,
    SessionState,
)

logger = logging.getLogger(__name__)

from vortexchain import (
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
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    max_http_buffer_size=2 * 1024 * 1024,  # 2MB per message
    ping_timeout=30,
    ping_interval=15,
)


@app.after_request
def add_cors(response):
    """Allow cross-origin requests for the public API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ---------------------------------------------------------------------------
# State — all in-memory for the dev server
# ---------------------------------------------------------------------------

session_manager = SessionManager()

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


@app.route("/demo")
def vrc48m_demo():
    """Public-facing VRC-48M demo page."""
    return send_file(Path(__file__).parent / "demo.html")


@app.route("/api/vrc48m/anchor", methods=["POST"])
def vrc48m_anchor():
    """Upload media and create a topological anchor."""
    from vortexchain.vrc48m import (
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
    from vortexchain.vrc48m import (
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
    from vortexchain.vrc48m import compare_media

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


@app.route("/api/vrc48m/anchor/<anchor_id>")
def vrc48m_get_anchor(anchor_id: str):
    """Get a specific anchor by ID."""
    if anchor_id not in media_anchors:
        return err(f"Unknown anchor: {anchor_id}", 404)
    a = media_anchors[anchor_id]["anchor"]
    return ok({
        "anchor_id": anchor_id,
        "filename": Path(a.file_path).name,
        "frame_count": a.frame_count,
        "duration_ms": a.duration_ms,
        "resolution": f"{a.width}x{a.height}",
        "chunks": len(a.chunk_spectra),
        "merkle_root": a.video_merkle_root,
        "chunk_spectra": a.chunk_spectra,
        "sample_spectra": a.sample_spectra,
        "processing_time_ms": round(a.processing_time_ms, 1),
        "created": media_anchors[anchor_id]["created"],
    })


@app.route("/api/vrc48m/anchor/<anchor_id>/download")
def vrc48m_download_anchor(anchor_id: str):
    """Download anchor as JSON file."""
    if anchor_id not in media_anchors:
        return err(f"Unknown anchor: {anchor_id}", 404)
    anchor_path = ANCHOR_DIR / f"{anchor_id}.json"
    if anchor_path.exists():
        return send_file(
            str(anchor_path),
            mimetype="application/json",
            as_attachment=True,
            download_name=f"{anchor_id}.json",
        )
    return err("Anchor file not found on disk", 404)


# ---------------------------------------------------------------------------
# Routes — WebSocket streaming for VRC-48M live capture
# ---------------------------------------------------------------------------

FRAME_ACK_INTERVAL = 10  # ACK every Nth frame to reduce chatter


@socketio.on("vrc48m:init")
def handle_vrc48m_init(data):
    """Start a new streaming session."""
    try:
        config = SessionConfig(
            fps=float(data.get("fps", 30.0)),
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            chunk_size=int(data.get("chunk_size", 10)),
            frame_skip=int(data.get("frame_skip", 3)),
            source_fps=float(data.get("source_fps", data.get("fps", 30.0))),
        )
        session = session_manager.create_session(request.sid, config)
        emit("vrc48m:session_created", {
            "session_id": session.session_id,
            "config": config.to_dict(),
        })
        logger.info("WS session created: %s for socket %s", session.session_id, request.sid)
    except Exception as e:
        emit("vrc48m:error", {"code": "INIT_FAILED", "message": str(e)})


@socketio.on("vrc48m:frame")
def handle_vrc48m_frame(data):
    """Process a binary frame message.

    Binary layout: [36B session_id ASCII][4B seq uint32 BE][JPEG bytes]
    """
    try:
        if not isinstance(data, (bytes, bytearray)):
            emit("vrc48m:error", {"code": "INVALID_FRAME", "message": "Expected binary data"})
            return

        if len(data) < 41:  # 36 + 4 + at least 1 byte JPEG
            emit("vrc48m:error", {"code": "INVALID_FRAME", "message": "Frame too short"})
            return

        session_id = data[:36].decode("ascii").strip()
        frame_seq = struct.unpack(">I", data[36:40])[0]
        jpeg_data = bytes(data[40:])

        session = session_manager.get_session(session_id)
        if session is None:
            emit("vrc48m:error", {
                "code": "UNKNOWN_SESSION",
                "message": f"No session: {session_id}",
                "session_id": session_id,
            })
            return

        chunk_result = session.process_frame(jpeg_data)

        # ACK every Nth frame
        if session.frame_count % FRAME_ACK_INTERVAL == 0:
            emit("vrc48m:frame_ack", {
                "session_id": session_id,
                "frame_index": session.frame_count,
            })

        # Emit chunk result if boundary was reached
        if chunk_result is not None:
            emit("vrc48m:chunk_complete", chunk_result)

    except ValueError as e:
        emit("vrc48m:error", {"code": "DECODE_FAILED", "message": str(e)})
    except RuntimeError as e:
        emit("vrc48m:error", {"code": "SESSION_ERROR", "message": str(e)})
    except Exception as e:
        logger.exception("Unexpected error in frame handler")
        emit("vrc48m:error", {"code": "INTERNAL_ERROR", "message": str(e)})


@socketio.on("vrc48m:finalize")
def handle_vrc48m_finalize(data):
    """Finalize a streaming session and return the anchor."""
    try:
        session_id = data.get("session_id", "")
        session = session_manager.get_session(session_id)
        if session is None:
            emit("vrc48m:error", {
                "code": "UNKNOWN_SESSION",
                "message": f"No session: {session_id}",
            })
            return

        result = session.finalize()

        # Also store in the REST-accessible media_anchors dict
        anchor_id = f"vrc48m_live_{int(time.time())}_{session_id[:8]}"
        # Create a minimal anchor-like object for the REST endpoints
        from types import SimpleNamespace
        anchor_ns = SimpleNamespace(**result["anchor"])
        anchor_ns.chunk_spectra = result["anchor"]["chunk_spectra"]
        anchor_ns.chunk_digests = result["anchor"]["chunk_digests"]
        anchor_ns.sample_spectra = result["anchor"]["sample_spectra"]
        media_anchors[anchor_id] = {
            "anchor": anchor_ns,
            "filepath": "<live-stream>",
            "created": time.time(),
        }
        result["anchor_id"] = anchor_id

        emit("vrc48m:anchor_complete", result)
        logger.info("WS session %s anchor complete: %s", session_id, anchor_id)

    except Exception as e:
        emit("vrc48m:error", {"code": "FINALIZE_FAILED", "message": str(e)})


@socketio.on("vrc48m:abort")
def handle_vrc48m_abort(data):
    """Abort a streaming session."""
    try:
        session_id = data.get("session_id", "")
        session = session_manager.get_session(session_id)
        if session:
            session.abort()
            emit("vrc48m:error", {
                "code": "ABORTED",
                "message": "Session aborted",
                "session_id": session_id,
            })
            session_manager.remove_session(session_id)
        else:
            emit("vrc48m:error", {
                "code": "UNKNOWN_SESSION",
                "message": f"No session: {session_id}",
            })
    except Exception as e:
        emit("vrc48m:error", {"code": "ABORT_ERROR", "message": str(e)})


@socketio.on("disconnect")
def handle_disconnect():
    """Clean up sessions on socket disconnect."""
    session_manager.cleanup_socket(request.sid)
    logger.info("Socket disconnected: %s", request.sid)


@socketio.on("connect")
def handle_connect():
    """Log new connections."""
    logger.info("Socket connected: %s", request.sid)


# Background session reaper
def _reaper_loop():
    """Periodically clean up stale sessions."""
    while True:
        socketio.sleep(30)
        reaped = session_manager.reap_stale()
        if reaped:
            logger.info("Reaped %d stale session(s)", reaped)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n  +--------------------------------------------------+")
    print("  |         VortexChain Dev Server v0.3.0            |")
    print("  |     Topological OAM Cryptography Protocol        |")
    print("  +--------------------------------------------------+")
    print("  |  Dashboard:     http://localhost:5000             |")
    print("  |  VRC-48M Demo:  http://localhost:5000/demo       |")
    print("  |  VRC-48M Dev:   http://localhost:5000/vrc48m     |")
    print("  |  API:           http://localhost:5000/api/chain  |")
    print("  |  WebSocket:     ws://localhost:5000 (VRC-48M)    |")
    print("  +--------------------------------------------------+\n")
    socketio.start_background_task(_reaper_loop)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
