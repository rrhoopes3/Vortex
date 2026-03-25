"""Solana on-chain anchor publishing for VRC-48M MediaAnchors.

Publishes the Merkle root and compact metadata to Solana via the Memo Program,
creating an immutable on-chain record that anyone can verify media provenance
against.

Dependencies (optional -- graceful degradation if missing):
    pip install solders solana

Usage (CLI):
    python -m vortexchain.vrc48m publish anchor.json [--rpc-url URL] [--keypair PATH]

Usage (Python):
    from vortexchain.solana_anchor import SolanaAnchorPublisher

    publisher = SolanaAnchorPublisher()
    tx = await publisher.publish_anchor(anchor)
    print(tx.explorer_url)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful imports for Solana SDK
# ---------------------------------------------------------------------------

_SOLANA_AVAILABLE = False
_SOLANA_IMPORT_ERROR: Optional[str] = None

try:
    from solders.keypair import Keypair  # type: ignore[import-untyped]
    from solders.pubkey import Pubkey  # type: ignore[import-untyped]
    from solders.transaction import Transaction as SolanaTransaction  # type: ignore[import-untyped]
    from solders.instruction import Instruction as SolanaInstruction  # type: ignore[import-untyped]
    from solders.message import Message as SolanaMessage  # type: ignore[import-untyped]
    from solders.hash import Hash as SolanaHash  # type: ignore[import-untyped]
    from solders.commitment_config import CommitmentLevel  # type: ignore[import-untyped]
    from solana.rpc.async_api import AsyncClient  # type: ignore[import-untyped]
    from solana.rpc.commitment import Confirmed  # type: ignore[import-untyped]

    _SOLANA_AVAILABLE = True
except ImportError as exc:
    _SOLANA_IMPORT_ERROR = (
        f"Solana SDK packages not installed: {exc}. "
        "Install them with: pip install solders solana"
    )


def _require_solana() -> None:
    """Raise a clear error if the Solana SDK is not available."""
    if not _SOLANA_AVAILABLE:
        raise RuntimeError(
            f"Solana on-chain features require the 'solders' and 'solana' packages.\n"
            f"{_SOLANA_IMPORT_ERROR}\n"
            f"Install with:  pip install solders solana"
        )


# ---------------------------------------------------------------------------
# Solana Memo Program
# ---------------------------------------------------------------------------

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
SOLSCAN_BASE_URL = "https://solscan.io/tx"
EXPLORER_BASE_URL = "https://explorer.solana.com/tx"

# On-chain payload version
ANCHOR_PAYLOAD_VERSION = 1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AnchorTransaction:
    """Result of publishing (or looking up) a VRC-48M anchor on Solana."""

    signature: str
    """Solana transaction signature (base-58)."""

    merkle_root: str
    """Merkle root of the media anchor (hex string)."""

    block_time: int
    """Unix timestamp of the block that included this transaction."""

    slot: int
    """Solana slot number."""

    memo_data: dict
    """Full decoded memo payload that was written on-chain."""

    explorer_url: str
    """Link to view the transaction on Solana Explorer / Solscan."""

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary."""
        return {
            "signature": self.signature,
            "merkle_root": self.merkle_root,
            "block_time": self.block_time,
            "slot": self.slot,
            "memo_data": self.memo_data,
            "explorer_url": self.explorer_url,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Anchor payload construction
# ---------------------------------------------------------------------------

def _build_memo_payload(anchor: Any, memo: str = "") -> dict:
    """Build the compact JSON memo payload from a MediaAnchor.

    The payload is kept minimal to reduce on-chain storage cost while
    retaining enough information for independent verification.

    Parameters
    ----------
    anchor:
        A ``MediaAnchor`` instance (imported lazily to avoid circular deps).
    memo:
        Optional human-readable note appended to the payload.

    Returns
    -------
    dict
        The memo payload dictionary matching the VRC-48M on-chain format.
    """
    payload: Dict[str, Any] = {
        "v": ANCHOR_PAYLOAD_VERSION,
        "std": "VRC-48M",
        "root": anchor.video_merkle_root,
        "frames": anchor.frame_count,
        "chunks": len(anchor.chunk_spectra),
        "w": anchor.width,
        "h": anchor.height,
        "fps": anchor.fps,
        "t": int(anchor.timestamp),
    }
    if memo:
        payload["memo"] = memo
    return payload


def _payload_to_bytes(payload: dict) -> bytes:
    """Serialize the memo payload to compact JSON bytes (no extra whitespace)."""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

class SolanaAnchorPublisher:
    """Publishes VRC-48M MediaAnchor Merkle roots to Solana.

    Uses the Solana Memo Program to embed a compact JSON payload on-chain,
    making media provenance verifiable against an immutable ledger.

    Parameters
    ----------
    rpc_url:
        Solana JSON-RPC endpoint.  Defaults to devnet.
    keypair_path:
        Optional filesystem path to a Solana CLI keypair JSON file.
        If ``None``, a new ephemeral keypair is generated (useful for
        testing but obviously not for production).
    """

    def __init__(
        self,
        rpc_url: str = "https://api.devnet.solana.com",
        keypair_path: Optional[str] = None,
    ) -> None:
        _require_solana()

        self.rpc_url = rpc_url
        self._keypair: Keypair = self._load_keypair(keypair_path)
        self._client: Optional[AsyncClient] = None

    # -- Keypair helpers ----------------------------------------------------

    @staticmethod
    def _load_keypair(path: Optional[str]) -> "Keypair":
        """Load a Solana keypair from a JSON file or generate an ephemeral one.

        Parameters
        ----------
        path:
            Path to a JSON file containing a 64-byte secret key array
            (standard ``solana-keygen`` format).  If ``None``, a fresh
            keypair is generated.

        Returns
        -------
        Keypair
            A ``solders.keypair.Keypair`` instance.

        Raises
        ------
        FileNotFoundError
            If *path* is given but does not exist.
        ValueError
            If the file content is not a valid keypair.
        """
        if path is None:
            kp = Keypair()
            logger.warning(
                "No keypair file provided -- using ephemeral keypair %s. "
                "Fund it with: solana airdrop 1 %s --url devnet",
                kp.pubkey(),
                kp.pubkey(),
            )
            return kp

        key_path = Path(path).expanduser()
        if not key_path.exists():
            raise FileNotFoundError(f"Keypair file not found: {key_path}")

        try:
            secret = json.loads(key_path.read_text())
            if isinstance(secret, list) and len(secret) == 64:
                return Keypair.from_bytes(bytes(secret))
            raise ValueError("Expected a JSON array of 64 integers")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid keypair file {key_path}: {exc}"
            ) from exc

    # -- RPC client ---------------------------------------------------------

    async def _get_client(self) -> "AsyncClient":
        """Return (and lazily create) the async RPC client."""
        if self._client is None:
            self._client = AsyncClient(self.rpc_url)
        return self._client

    async def close(self) -> None:
        """Close the underlying RPC connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # -- Core operations ----------------------------------------------------

    async def publish_anchor(
        self,
        anchor: Any,
        memo: str = "",
    ) -> AnchorTransaction:
        """Publish a MediaAnchor's Merkle root to Solana via the Memo Program.

        Parameters
        ----------
        anchor:
            A ``MediaAnchor`` instance whose ``video_merkle_root`` will be
            recorded on-chain.
        memo:
            Optional human-readable memo string included in the payload.

        Returns
        -------
        AnchorTransaction
            Details of the confirmed on-chain transaction.

        Raises
        ------
        RuntimeError
            On network failure, insufficient SOL balance, or transaction error.
        """
        client = await self._get_client()

        # Build the memo payload
        payload = _build_memo_payload(anchor, memo)
        payload_bytes = _payload_to_bytes(payload)

        logger.info(
            "Publishing anchor root=%s (%d bytes memo) to %s",
            anchor.video_merkle_root[:16] + "...",
            len(payload_bytes),
            self.rpc_url,
        )

        # Check balance before sending
        try:
            balance_resp = await client.get_balance(self._keypair.pubkey())
            lamports = balance_resp.value
            if lamports < 10_000:
                raise RuntimeError(
                    f"Insufficient SOL balance: {lamports} lamports "
                    f"(~{lamports / 1e9:.6f} SOL).  "
                    f"Fund with: solana airdrop 1 {self._keypair.pubkey()} --url devnet"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to check balance at {self.rpc_url}: {exc}"
            ) from exc

        # Build the memo instruction
        memo_program = Pubkey.from_string(MEMO_PROGRAM_ID)
        memo_ix = SolanaInstruction(
            program_id=memo_program,
            accounts=[],
            data=payload_bytes,
        )

        # Get a recent blockhash
        try:
            blockhash_resp = await client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch recent blockhash from {self.rpc_url}: {exc}"
            ) from exc

        # Build and sign the transaction
        msg = SolanaMessage.new_with_blockhash(
            [memo_ix],
            self._keypair.pubkey(),
            recent_blockhash,
        )
        tx = SolanaTransaction.new_unsigned(msg)
        tx.sign([self._keypair], recent_blockhash)

        # Send and confirm
        try:
            send_resp = await client.send_transaction(tx)
            signature = str(send_resp.value)
        except Exception as exc:
            raise RuntimeError(
                f"Transaction send failed: {exc}"
            ) from exc

        logger.info("Transaction sent: %s -- awaiting confirmation...", signature)

        # Wait for confirmation
        try:
            await client.confirm_transaction(
                signature,
                commitment="confirmed",
            )
        except Exception as exc:
            raise RuntimeError(
                f"Transaction confirmation failed for {signature}: {exc}"
            ) from exc

        # Fetch transaction details for block_time and slot
        block_time = int(time.time())
        slot = 0
        try:
            tx_resp = await client.get_transaction(
                signature,
                encoding="json",
            )
            if tx_resp.value is not None:
                slot = tx_resp.value.slot
                if tx_resp.value.block_time is not None:
                    block_time = tx_resp.value.block_time
        except Exception:
            logger.warning(
                "Could not fetch tx details for %s; using local timestamp",
                signature,
            )

        # Determine explorer URL based on RPC endpoint
        cluster_param = self._cluster_param()
        explorer_url = f"{SOLSCAN_BASE_URL}/{signature}{cluster_param}"

        return AnchorTransaction(
            signature=signature,
            merkle_root=anchor.video_merkle_root,
            block_time=block_time,
            slot=slot,
            memo_data=payload,
            explorer_url=explorer_url,
        )

    async def verify_on_chain(
        self,
        anchor: Any,
        tx_signature: str,
    ) -> bool:
        """Verify that an on-chain transaction matches the given anchor.

        Fetches the transaction from Solana, decodes the memo payload, and
        checks that the ``root`` field matches ``anchor.video_merkle_root``.

        Parameters
        ----------
        anchor:
            A ``MediaAnchor`` to verify against.
        tx_signature:
            The Solana transaction signature (base-58) to look up.

        Returns
        -------
        bool
            ``True`` if the on-chain Merkle root matches the anchor's root.

        Raises
        ------
        RuntimeError
            If the transaction cannot be fetched or does not contain a
            valid VRC-48M memo.
        """
        client = await self._get_client()

        try:
            tx_resp = await client.get_transaction(
                tx_signature,
                encoding="json",
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch transaction {tx_signature}: {exc}"
            ) from exc

        if tx_resp.value is None:
            raise RuntimeError(
                f"Transaction not found: {tx_signature}"
            )

        # Extract memo data from the transaction log messages
        memo_payload = self._extract_memo_from_tx(tx_resp.value)
        if memo_payload is None:
            raise RuntimeError(
                f"No VRC-48M memo found in transaction {tx_signature}"
            )

        on_chain_root = memo_payload.get("root", "")
        matches = on_chain_root == anchor.video_merkle_root

        if matches:
            logger.info(
                "On-chain verification PASSED: root=%s tx=%s",
                on_chain_root[:16] + "...",
                tx_signature[:16] + "...",
            )
        else:
            logger.warning(
                "On-chain verification FAILED: chain=%s != anchor=%s",
                on_chain_root[:16] + "...",
                anchor.video_merkle_root[:16] + "...",
            )

        return matches

    async def lookup_anchor(
        self,
        merkle_root_hex: str,
    ) -> Optional[AnchorTransaction]:
        """Search for an anchor by Merkle root in recent transactions.

        Scans the publishing keypair's recent transaction signatures looking
        for a memo whose ``root`` field matches *merkle_root_hex*.

        Parameters
        ----------
        merkle_root_hex:
            The Merkle root (hex string) to search for.

        Returns
        -------
        AnchorTransaction or None
            The matching transaction, or ``None`` if not found.

        Note
        ----
        This performs a linear scan over the keypair's recent transactions
        (up to 100) and is intended for devnet/testnet use.  For production
        use a dedicated indexer or database of published anchors.
        """
        client = await self._get_client()

        try:
            sigs_resp = await client.get_signatures_for_address(
                self._keypair.pubkey(),
                limit=100,
            )
        except Exception as exc:
            logger.error("Failed to fetch signatures: %s", exc)
            return None

        for sig_info in sigs_resp.value:
            sig = str(sig_info.signature)
            try:
                tx_resp = await client.get_transaction(sig, encoding="json")
                if tx_resp.value is None:
                    continue

                memo = self._extract_memo_from_tx(tx_resp.value)
                if memo is not None and memo.get("root") == merkle_root_hex:
                    block_time = (
                        tx_resp.value.block_time
                        if tx_resp.value.block_time is not None
                        else 0
                    )
                    cluster_param = self._cluster_param()
                    return AnchorTransaction(
                        signature=sig,
                        merkle_root=merkle_root_hex,
                        block_time=block_time,
                        slot=tx_resp.value.slot,
                        memo_data=memo,
                        explorer_url=f"{SOLSCAN_BASE_URL}/{sig}{cluster_param}",
                    )
            except Exception:
                continue

        return None

    # -- Helpers ------------------------------------------------------------

    def _cluster_param(self) -> str:
        """Return the Solscan cluster query param based on RPC URL."""
        url = self.rpc_url.lower()
        if "devnet" in url:
            return "?cluster=devnet"
        elif "testnet" in url:
            return "?cluster=testnet"
        return ""

    @staticmethod
    def _extract_memo_from_tx(tx_value: Any) -> Optional[dict]:
        """Extract and decode a VRC-48M memo payload from transaction data.

        Parameters
        ----------
        tx_value:
            The transaction value object from ``get_transaction``.

        Returns
        -------
        dict or None
            The decoded memo payload, or ``None`` if no valid VRC-48M memo
            was found.
        """
        try:
            # The memo program logs the memo content in the transaction logs.
            # We look for it in the log messages.
            if hasattr(tx_value, "transaction"):
                meta = tx_value.transaction.meta
                if meta is not None and hasattr(meta, "log_messages"):
                    for log in (meta.log_messages or []):
                        log_str = str(log)
                        # Memo program logs: "Program log: Memo (len N): <data>"
                        if "Memo" in log_str and "{" in log_str:
                            json_start = log_str.index("{")
                            json_str = log_str[json_start:]
                            payload = json.loads(json_str)
                            if payload.get("std") == "VRC-48M":
                                return payload
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

        # Fallback: try parsing instruction data directly
        try:
            if hasattr(tx_value, "transaction"):
                message = tx_value.transaction.transaction.message
                for ix in message.instructions:
                    try:
                        data_bytes = bytes(ix.data)
                        payload = json.loads(data_bytes.decode("utf-8"))
                        if payload.get("std") == "VRC-48M":
                            return payload
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
        except (AttributeError, TypeError):
            pass

        return None

    @property
    def pubkey(self) -> str:
        """Return the publisher's public key as a base-58 string."""
        return str(self._keypair.pubkey())


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def cli_publish(args: List[str]) -> int:
    """CLI handler for publishing a MediaAnchor to Solana.

    Designed to be wired into the existing vrc48m CLI:

        python -m vortexchain.vrc48m publish anchor.json [--rpc-url URL] [--keypair PATH]

    Parameters
    ----------
    args:
        Command-line arguments after the ``publish`` subcommand.

    Returns
    -------
    int
        Exit code (0 on success, 1 on failure).
    """
    if not args:
        print("Usage: python -m vortexchain.vrc48m publish <anchor.json> "
              "[--rpc-url URL] [--keypair PATH] [--memo TEXT]")
        return 1

    anchor_path = args[0]
    rpc_url = "https://api.devnet.solana.com"
    keypair_path: Optional[str] = None
    memo = ""

    # Parse optional flags
    i = 1
    while i < len(args):
        if args[i] == "--rpc-url" and i + 1 < len(args):
            rpc_url = args[i + 1]
            i += 2
        elif args[i] == "--keypair" and i + 1 < len(args):
            keypair_path = args[i + 1]
            i += 2
        elif args[i] == "--memo" and i + 1 < len(args):
            memo = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}")
            return 1

    # Load anchor
    anchor_file = Path(anchor_path)
    if not anchor_file.exists():
        print(f"Error: Anchor file not found: {anchor_path}")
        return 1

    try:
        from vortexchain.vrc48m import MediaAnchor

        anchor = MediaAnchor.load(str(anchor_file))
    except Exception as exc:
        print(f"Error: Failed to load anchor: {exc}")
        return 1

    # Publish
    try:
        _require_solana()
        publisher = SolanaAnchorPublisher(
            rpc_url=rpc_url,
            keypair_path=keypair_path,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Publishing VRC-48M anchor to Solana...")
    print(f"  RPC:         {rpc_url}")
    print(f"  Keypair:     {keypair_path or '(ephemeral)'}")
    print(f"  Merkle root: {anchor.video_merkle_root[:32]}...")
    print(f"  Frames:      {anchor.frame_count}")
    print(f"  Resolution:  {anchor.width}x{anchor.height}")
    print()

    try:
        tx = asyncio.run(_cli_publish_async(publisher, anchor, memo))
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 1

    print(f"Anchor published successfully!")
    print(f"  Signature: {tx.signature}")
    print(f"  Slot:      {tx.slot}")
    print(f"  Explorer:  {tx.explorer_url}")
    print()
    print(f"On-chain payload:")
    print(f"  {json.dumps(tx.memo_data, indent=2)}")

    return 0


async def _cli_publish_async(
    publisher: SolanaAnchorPublisher,
    anchor: Any,
    memo: str,
) -> AnchorTransaction:
    """Async helper for the CLI publish flow."""
    try:
        return await publisher.publish_anchor(anchor, memo)
    finally:
        await publisher.close()


# ---------------------------------------------------------------------------
# Server route examples (for integration into vortexchain/server.py)
# ---------------------------------------------------------------------------

# The following Flask route stubs show how to integrate Solana anchor
# publishing into the existing VRC-48M server endpoints.  Copy them
# into vortexchain/server.py inside the VRC-48M routes section.
#
# --- POST /api/vrc48m/anchor/<id>/publish ---
#
#   @app.route("/api/vrc48m/anchor/<anchor_id>/publish", methods=["POST"])
#   def vrc48m_publish_anchor(anchor_id: str):
#       """Publish an existing anchor's Merkle root to Solana."""
#       from vortexchain.solana_anchor import SolanaAnchorPublisher
#
#       if anchor_id not in media_anchors:
#           return err(f"Unknown anchor: {anchor_id}", 404)
#
#       body = request.get_json(silent=True) or {}
#       rpc_url = body.get("rpc_url", "https://api.devnet.solana.com")
#       keypair_path = body.get("keypair_path")
#       memo = body.get("memo", "")
#
#       anchor = media_anchors[anchor_id]["anchor"]
#
#       try:
#           publisher = SolanaAnchorPublisher(
#               rpc_url=rpc_url,
#               keypair_path=keypair_path,
#           )
#
#           import asyncio
#           loop = asyncio.new_event_loop()
#           try:
#               tx = loop.run_until_complete(
#                   publisher.publish_anchor(anchor, memo)
#               )
#           finally:
#               loop.run_until_complete(publisher.close())
#               loop.close()
#
#           # Store the chain record alongside the anchor
#           media_anchors[anchor_id]["solana_tx"] = tx.to_dict()
#
#           return ok({
#               "anchor_id": anchor_id,
#               "signature": tx.signature,
#               "slot": tx.slot,
#               "block_time": tx.block_time,
#               "explorer_url": tx.explorer_url,
#               "memo_data": tx.memo_data,
#           })
#       except RuntimeError as e:
#           return err(f"Solana publish failed: {str(e)}")
#       except Exception as e:
#           return err(f"Unexpected error: {str(e)}")
#
#
# --- GET /api/vrc48m/anchor/<id>/chain ---
#
#   @app.route("/api/vrc48m/anchor/<anchor_id>/chain")
#   def vrc48m_chain_status(anchor_id: str):
#       """Check on-chain status for a published anchor."""
#       if anchor_id not in media_anchors:
#           return err(f"Unknown anchor: {anchor_id}", 404)
#
#       info = media_anchors[anchor_id]
#       solana_tx = info.get("solana_tx")
#
#       if solana_tx is None:
#           return ok({
#               "anchor_id": anchor_id,
#               "on_chain": False,
#               "message": "Anchor has not been published to Solana yet.",
#           })
#
#       # Optionally re-verify on chain
#       verified = None
#       verify_param = request.args.get("verify", "false")
#       if verify_param.lower() == "true":
#           try:
#               from vortexchain.solana_anchor import SolanaAnchorPublisher
#
#               rpc_url = request.args.get(
#                   "rpc_url", "https://api.devnet.solana.com"
#               )
#               publisher = SolanaAnchorPublisher(rpc_url=rpc_url)
#
#               import asyncio
#               loop = asyncio.new_event_loop()
#               try:
#                   verified = loop.run_until_complete(
#                       publisher.verify_on_chain(
#                           info["anchor"], solana_tx["signature"]
#                       )
#                   )
#               finally:
#                   loop.run_until_complete(publisher.close())
#                   loop.close()
#           except Exception as e:
#               verified = None
#               logger.warning("On-chain verify failed: %s", e)
#
#       result = {
#           "anchor_id": anchor_id,
#           "on_chain": True,
#           "signature": solana_tx["signature"],
#           "slot": solana_tx["slot"],
#           "block_time": solana_tx["block_time"],
#           "explorer_url": solana_tx["explorer_url"],
#           "memo_data": solana_tx["memo_data"],
#       }
#       if verified is not None:
#           result["verified"] = verified
#
#       return ok(result)
