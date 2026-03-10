"""
Solana USDC Watcher — polls for incoming USDC transfers and auto-credits agent wallets.

Flow:
  1. Poll getSignaturesForAddress for new transactions to our USDC receiver wallet
  2. For each new signature, fetch the full transaction via getTransaction
  3. Extract SPL Memo (agent identifier: inv_xxx or ext_xxx)
  4. Extract USDC transfer amount from parsed token instructions
  5. Resolve agent_id from memo (invoice lookup or direct agent name)
  6. Credit the agent's wallet via ledger.deposit()
  7. Record the signature in processed_solana_txs for idempotency

No private keys needed — read-only watching only.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from forge.toll.ledger import Ledger

log = logging.getLogger("forge.toll.solana_watcher")

# SPL Memo program IDs (both v1 and v2)
MEMO_PROGRAM_IDS = {
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",  # Memo v2
    "Memo1UhkJBfCR6MNLc6LzN7E6qoRFkYS5A7EN7wrV3",    # Memo v1
}


class SolanaUSDCWatcher:
    """Background watcher that polls Solana for incoming USDC transfers."""

    def __init__(self, ledger: Ledger, rpc_url: str, receiver_address: str,
                 usdc_mint: str, poll_interval: int = 15, usdc_decimals: int = 6):
        self.ledger = ledger
        self.rpc_url = rpc_url
        self.receiver_address = receiver_address
        self.usdc_mint = usdc_mint
        self.poll_interval = poll_interval
        self.usdc_decimals = usdc_decimals
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_signature: str | None = None

    def start(self) -> None:
        """Start the watcher in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            log.warning("Solana watcher already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="solana-usdc-watcher")
        self._thread.start()
        log.info("Solana USDC watcher started (receiver=%s, interval=%ds)",
                 self.receiver_address, self.poll_interval)

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Solana USDC watcher stopped")

    def _poll_loop(self) -> None:
        """Main polling loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:
                log.exception("Solana watcher poll error")
            self._stop_event.wait(self.poll_interval)

    def _poll_once(self) -> None:
        """Single poll iteration: fetch new signatures and process them."""
        signatures = self._get_recent_signatures()
        if not signatures:
            return

        for sig_info in signatures:
            sig = sig_info.get("signature", "")
            if not sig:
                continue

            # Skip if already processed (idempotency)
            if self.ledger.is_solana_tx_processed(sig):
                continue

            # Skip failed transactions
            if sig_info.get("err") is not None:
                self.ledger.record_solana_tx(sig)
                continue

            self._process_transaction(sig)

    def _get_recent_signatures(self, limit: int = 20) -> list[dict]:
        """Fetch recent transaction signatures for the receiver address."""
        params: list = [
            self.receiver_address,
            {"limit": limit, "commitment": "confirmed"},
        ]
        if self._last_signature:
            params[1]["until"] = self._last_signature

        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignaturesForAddress",
            "params": params,
        }
        try:
            resp = requests.post(self.rpc_url, json=payload, timeout=10)
            data = resp.json()
            sigs = data.get("result", [])
            # Update cursor for next poll
            if sigs:
                self._last_signature = sigs[0]["signature"]
            return sigs
        except Exception:
            log.exception("Failed to fetch Solana signatures")
            return []

    def _process_transaction(self, signature: str) -> None:
        """Fetch full transaction, extract memo + USDC amount, credit agent."""
        tx_data = self._get_transaction(signature)
        if not tx_data:
            self.ledger.record_solana_tx(signature)
            return

        memo = self._extract_memo(tx_data)
        usdc_amount = self._extract_usdc_amount(tx_data)

        if not memo or usdc_amount <= 0:
            log.debug("Skipping tx %s: no memo or zero USDC (memo=%s, amount=%.6f)",
                      signature[:16], memo, usdc_amount)
            self.ledger.record_solana_tx(signature)
            return

        # Resolve agent from memo
        agent_id, invoice_id = self._resolve_agent(memo)
        if not agent_id:
            log.warning("Could not resolve agent from memo '%s' (tx=%s)", memo, signature[:16])
            self.ledger.record_solana_tx(signature)
            return

        # Credit the agent's wallet
        usd_amount = usdc_amount  # 1 USDC = 1 USD
        self.ledger.deposit(agent_id, usd_amount)

        # Mark invoice as paid if applicable
        if invoice_id:
            self.ledger.mark_invoice_paid(invoice_id, signature, usdc_amount)

        # Record processed tx for idempotency
        self.ledger.record_solana_tx(signature, agent_id, usdc_amount, invoice_id)

        log.info("Credited agent %s with $%.6f USDC (tx=%s, invoice=%s)",
                 agent_id, usd_amount, signature[:16], invoice_id or "none")

    def _get_transaction(self, signature: str) -> dict | None:
        """Fetch a full parsed transaction from Solana RPC."""
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed",
                                   "maxSupportedTransactionVersion": 0}],
        }
        try:
            resp = requests.post(self.rpc_url, json=payload, timeout=10)
            data = resp.json()
            return data.get("result")
        except Exception:
            log.exception("Failed to fetch transaction %s", signature[:16])
            return None

    @staticmethod
    def _extract_memo(tx_data: dict) -> str:
        """Extract SPL Memo text from a parsed transaction."""
        try:
            instructions = (tx_data.get("transaction", {})
                           .get("message", {})
                           .get("instructions", []))
            # Also check inner instructions
            inner = (tx_data.get("meta", {})
                    .get("innerInstructions", []))
            all_instructions = list(instructions)
            for inner_group in inner:
                all_instructions.extend(inner_group.get("instructions", []))

            for ix in all_instructions:
                program_id = ix.get("programId", "")
                if program_id in MEMO_PROGRAM_IDS:
                    # Memo data is in the "parsed" field for jsonParsed encoding
                    parsed = ix.get("parsed", "")
                    if isinstance(parsed, str) and parsed:
                        return parsed.strip()
                    # Some encodings put it in "data"
                    data = ix.get("data", "")
                    if isinstance(data, str) and data:
                        return data.strip()
        except Exception:
            log.exception("Failed to extract memo")
        return ""

    def _extract_usdc_amount(self, tx_data: dict) -> float:
        """Extract USDC transfer amount from parsed token instructions."""
        try:
            # Check pre/post token balances for our receiver
            post_balances = tx_data.get("meta", {}).get("postTokenBalances", [])
            pre_balances = tx_data.get("meta", {}).get("preTokenBalances", [])

            # Build maps: accountIndex → uiAmount
            pre_map: dict[int, float] = {}
            for bal in pre_balances:
                if bal.get("mint") == self.usdc_mint:
                    owner = bal.get("owner", "")
                    if owner == self.receiver_address:
                        ui = bal.get("uiTokenAmount", {}).get("uiAmount")
                        pre_map[bal["accountIndex"]] = float(ui or 0)

            for bal in post_balances:
                if bal.get("mint") == self.usdc_mint:
                    owner = bal.get("owner", "")
                    if owner == self.receiver_address:
                        post_ui = float(bal.get("uiTokenAmount", {}).get("uiAmount") or 0)
                        pre_ui = pre_map.get(bal["accountIndex"], 0.0)
                        diff = post_ui - pre_ui
                        if diff > 0:
                            return round(diff, self.usdc_decimals)
        except Exception:
            log.exception("Failed to extract USDC amount")
        return 0.0

    def _resolve_agent(self, memo: str) -> tuple[str, str]:
        """Resolve an agent_id and optional invoice_id from a memo string.

        Supports:
          - "inv_xxx" → look up invoice in ledger → get agent_id
          - "ext_xxx" → direct agent ID
        Returns (agent_id, invoice_id) or ("", "").
        """
        memo = memo.strip()

        # Invoice-based resolution
        if memo.startswith("inv_"):
            inv = self.ledger.get_invoice(memo)
            if inv and inv.status == "pending":
                return inv.agent_id, inv.invoice_id
            log.debug("Invoice %s not found or not pending", memo)
            return "", ""

        # Direct agent ID resolution
        if memo.startswith("ext_"):
            wallet = self.ledger.get_wallet(memo)
            if wallet:
                return memo, ""
            log.debug("Agent %s not found in ledger", memo)
            return "", ""

        log.debug("Unrecognized memo format: %s", memo)
        return "", ""
