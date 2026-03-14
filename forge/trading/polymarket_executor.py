"""Polymarket CLOB execution layer.

Parses agent decisions like "BUY YES $20" and places real orders
via the Polymarket CLOB API (py-clob-client).

Requires env vars:
  FORGE_POLYMARKET_PRIVATE_KEY   — exported from Polymarket.com
  FORGE_POLYMARKET_FUNDER_ADDRESS — the wallet that holds your USDC
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Decision parsing ─────────────────────────────────────────────────────────

@dataclass
class TradeDecision:
    action: str        # "BUY" or "HOLD"
    side: str          # "YES" or "NO"
    amount_usd: float  # dollar amount to spend
    reason: str        # the reasoning text

    @property
    def is_trade(self) -> bool:
        return self.action == "BUY" and self.amount_usd > 0


def parse_decision(text: str) -> TradeDecision:
    """Extract a trade decision from agent output text.

    Looks for patterns like:
      DECISION: BUY YES $20 — reason
      DECISION: BUY NO $15 — reason
      DECISION: HOLD — reason
      **DECISION: BUY YES $20** — reason
    """
    # Strip markdown bold
    clean = text.replace("**", "").replace("*", "")

    # Try to find DECISION line
    pattern = r"DECISION:\s*(BUY\s+(YES|NO|UP|DOWN)\s*\$?(\d+(?:\.\d+)?)|\bHOLD\b)"
    match = re.search(pattern, clean, re.IGNORECASE)

    if not match:
        # Fallback: look for just "BUY YES $X" or "BUY NO $X" anywhere
        fallback = re.search(r"\bBUY\s+(YES|NO|UP|DOWN)\s*\$?(\d+(?:\.\d+)?)", clean, re.IGNORECASE)
        if fallback:
            side = fallback.group(1).upper()
            # Normalize UP/DOWN to YES/NO
            if side == "UP":
                side = "YES"
            elif side == "DOWN":
                side = "NO"
            return TradeDecision(
                action="BUY",
                side=side,
                amount_usd=float(fallback.group(2)),
                reason=clean.strip(),
            )
        return TradeDecision(action="HOLD", side="", amount_usd=0, reason=clean.strip())

    full = match.group(0)
    if "HOLD" in full.upper():
        return TradeDecision(action="HOLD", side="", amount_usd=0, reason=clean.strip())

    side = match.group(2).upper()
    amount = float(match.group(3))

    # Normalize UP/DOWN to YES/NO
    if side == "UP":
        side = "YES"
    elif side == "DOWN":
        side = "NO"

    return TradeDecision(action="BUY", side=side, amount_usd=amount, reason=clean.strip())


# ── CLOB client setup ────────────────────────────────────────────────────────

_clob_client = None


def _get_client():
    """Lazy-init the Polymarket CLOB client."""
    global _clob_client
    if _clob_client is not None:
        return _clob_client

    from forge.config import (
        POLYMARKET_PRIVATE_KEY,
        POLYMARKET_FUNDER_ADDRESS,
        POLYMARKET_SIGNATURE_TYPE,
    )

    if not POLYMARKET_PRIVATE_KEY:
        raise RuntimeError(
            "FORGE_POLYMARKET_PRIVATE_KEY not set. "
            "Export your private key from Polymarket.com → Cash → ⋯ → Export Private Key"
        )

    from py_clob_client.client import ClobClient

    client = ClobClient(
        "https://clob.polymarket.com",
        key=POLYMARKET_PRIVATE_KEY,
        chain_id=137,  # Polygon mainnet
        signature_type=POLYMARKET_SIGNATURE_TYPE,
        funder=POLYMARKET_FUNDER_ADDRESS or None,
    )

    # Derive L2 API credentials for order placement
    try:
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        log.info("Polymarket CLOB client initialized (L2 creds derived)")
    except Exception as e:
        log.warning("Failed to derive L2 creds: %s — read-only mode", e)

    _clob_client = client
    return client


def is_configured() -> bool:
    """Check if Polymarket credentials are configured."""
    from forge.config import POLYMARKET_PRIVATE_KEY
    return bool(POLYMARKET_PRIVATE_KEY)


# ── Market resolution ────────────────────────────────────────────────────────

def resolve_token_id(condition_id: str, side: str) -> str | None:
    """Get the token_id for YES or NO outcome of a market.

    Args:
        condition_id: The market's condition ID (hex string)
        side: "YES" or "NO"
    """
    try:
        client = _get_client()
        market = client.get_market(condition_id)
        tokens = market.get("tokens", [])
        for t in tokens:
            outcome = t.get("outcome", "").upper()
            if outcome == side or (outcome == "UP" and side == "YES") or (outcome == "DOWN" and side == "NO"):
                return t.get("token_id")
        log.warning("No %s token found in market %s", side, condition_id)
        return None
    except Exception as e:
        log.error("Failed to resolve token_id for %s: %s", condition_id, e)
        return None


def get_market_price(token_id: str) -> float | None:
    """Get current midpoint price for a token."""
    try:
        client = _get_client()
        mid = client.get_midpoint(token_id)
        return float(mid) if mid else None
    except Exception as e:
        log.error("Failed to get price for %s: %s", token_id, e)
        return None


# ── Order execution ──────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    side: str = ""
    amount_usd: float = 0
    price: float = 0
    shares: float = 0
    error: str = ""

    def summary(self) -> str:
        if self.success:
            return (
                f"ORDER FILLED: {self.side} {self.shares:.1f} shares @ {self.price:.3f} "
                f"(${self.amount_usd:.2f})"
            )
        return f"ORDER FAILED: {self.error}"


def execute_market_order(
    condition_id: str,
    decision: TradeDecision,
    max_position_usd: float = 50.0,
    dry_run: bool = False,
) -> OrderResult:
    """Execute a market order based on an agent's trade decision.

    Args:
        condition_id: The market condition ID
        decision: Parsed trade decision
        max_position_usd: Safety cap on position size
        dry_run: If True, log but don't actually place the order
    """
    if not decision.is_trade:
        return OrderResult(success=True, side="HOLD", error="No trade (HOLD)")

    # Cap the amount
    amount = min(decision.amount_usd, max_position_usd)
    if amount <= 0:
        return OrderResult(success=False, error="Amount <= 0")

    # Resolve token
    token_id = resolve_token_id(condition_id, decision.side)
    if not token_id:
        return OrderResult(success=False, error=f"Could not resolve {decision.side} token_id")

    # Get current price
    price = get_market_price(token_id)
    if price is None:
        return OrderResult(success=False, error="Could not get market price")

    if price <= 0 or price >= 1:
        return OrderResult(success=False, error=f"Price {price} out of tradeable range")

    shares = amount / price

    log.info(
        "Polymarket order: %s %s %.1f shares @ %.3f ($%.2f) [condition=%s] %s",
        "DRY-RUN" if dry_run else "LIVE",
        decision.side, shares, price, amount, condition_id[:16],
        decision.reason[:80],
    )

    if dry_run:
        return OrderResult(
            success=True,
            side=decision.side,
            amount_usd=amount,
            price=price,
            shares=shares,
            error="DRY RUN — no order placed",
        )

    # Place actual market order (Fill-or-Kill)
    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        client = _get_client()
        order_args = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=BUY,
            order_type=OrderType.FOK,
        )
        signed = client.create_market_order(order_args)
        resp = client.post_order(signed, OrderType.FOK)

        order_id = ""
        if isinstance(resp, dict):
            order_id = resp.get("orderID", resp.get("id", ""))
            if resp.get("status") in ("matched", "filled", "MATCHED"):
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    side=decision.side,
                    amount_usd=amount,
                    price=price,
                    shares=shares,
                )
            else:
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    side=decision.side,
                    amount_usd=amount,
                    price=price,
                    error=f"Order status: {resp.get('status', 'unknown')} — {resp}",
                )

        return OrderResult(
            success=True,
            order_id=str(resp),
            side=decision.side,
            amount_usd=amount,
            price=price,
            shares=shares,
        )

    except Exception as e:
        log.error("Order execution failed: %s", e)
        return OrderResult(
            success=False,
            side=decision.side,
            amount_usd=amount,
            price=price,
            error=f"{type(e).__name__}: {e}",
        )
