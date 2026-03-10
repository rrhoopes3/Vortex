"""
HTTP 402 Payment Required toll gate for the agent marketplace.

The @toll_gate decorator checks an agent's wallet balance before allowing
a request through. If the balance is too low, it returns a 402 response
with payment instructions (x402 pattern).
"""
from __future__ import annotations

import functools
import logging
import uuid

from flask import g, jsonify

log = logging.getLogger("forge.toll.gating")


def toll_gate(estimate_usd: float = 0.05):
    """Decorator (runs AFTER @require_api_key) — checks wallet balance.

    If balance < estimate, returns HTTP 402 with payment methods.
    If balance sufficient, proceeds normally.

    Deficit tracking preserved: even if actual tolls exceed balance during
    execution, the task won't crash. Like real toll roads — the gate checks,
    but doesn't stop you mid-highway.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            from forge.config import (
                MARKETPLACE_BASE_USDC_ADDRESS,
                MARKETPLACE_SOLANA_USDC_ADDRESS,
            )

            agent_id = getattr(g, "agent_id", None)
            if not agent_id:
                return jsonify({"error": "authentication_required"}), 401

            ledger = _get_gate_ledger()
            balance = ledger.get_balance(agent_id)

            if balance < estimate_usd:
                shortfall = round(estimate_usd - balance, 8)
                invoice_id = f"inv_{uuid.uuid4().hex[:12]}"

                payment_methods = [
                    {"type": "api_deposit", "method": "POST /api/v1/wallet/deposit"},
                ]
                if MARKETPLACE_BASE_USDC_ADDRESS:
                    payment_methods.append({
                        "type": "base_usdc",
                        "chain_id": 8453,
                        "receiver": MARKETPLACE_BASE_USDC_ADDRESS,
                    })
                if MARKETPLACE_SOLANA_USDC_ADDRESS:
                    payment_methods.append({
                        "type": "solana_usdc",
                        "receiver": MARKETPLACE_SOLANA_USDC_ADDRESS,
                    })

                log.info("402 gate: agent=%s balance=%.6f estimate=%.6f shortfall=%.6f",
                         agent_id, balance, estimate_usd, shortfall)

                return jsonify({
                    "error": "payment_required",
                    "estimate_usd": estimate_usd,
                    "current_balance_usd": round(balance, 8),
                    "shortfall_usd": shortfall,
                    "invoice_id": invoice_id,
                    "payment_methods": payment_methods,
                }), 402

            return f(*args, **kwargs)
        return decorated
    return decorator


# Shared ledger for gating — lazy initialized
_gate_ledger = None


def _get_gate_ledger():
    global _gate_ledger
    if _gate_ledger is None:
        from forge.config import TOLL_DB_PATH
        from forge.toll.ledger import Ledger
        _gate_ledger = Ledger(TOLL_DB_PATH)
    return _gate_ledger
