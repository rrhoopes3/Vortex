"""Pydantic data models for the toll protocol."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _short_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Wallet(BaseModel):
    """Agent wallet — tracks balance and ownership."""
    wallet_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str
    owner_id: str = "system"
    balance_usd: float = 10.0
    total_deposited: float = 10.0
    total_spent: float = 0.0
    created_at: str = Field(default_factory=_now_iso)
    is_active: bool = True


class TollRate(BaseModel):
    """Configurable toll rate for a message type."""
    message_type: str
    base_rate_usd: float
    per_token_rate: float = 0.0
    creator_rake_pct: float = 30.0
    volume_discount_threshold: int = 100
    volume_discount_pct: float = 10.0


class TollMessage(BaseModel):
    """A metered inter-agent message with toll metadata."""
    message_id: str = Field(default_factory=_short_id)
    sender: str
    receiver: str
    message_type: str
    payload_summary: str = ""
    token_count: int = 0
    toll_amount_usd: float = 0.0
    creator_revenue_usd: float = 0.0
    tx_hash: str = ""
    timestamp: str = Field(default_factory=_now_iso)
    session_id: str = ""
    hop_number: int = 1


class Transaction(BaseModel):
    """Ledger transaction record."""
    tx_id: str = Field(default_factory=_short_id)
    tx_type: Literal["toll", "deposit", "withdrawal", "refund", "creator_payout"] = "toll"
    from_wallet: str
    to_wallet: str
    amount_usd: float
    toll_message_id: str = ""
    description: str = ""
    timestamp: str = Field(default_factory=_now_iso)
    settlement_status: Literal["local", "pending_chain", "settled_chain"] = "local"
    chain_tx_hash: str = ""


class TollReceipt(BaseModel):
    """Receipt returned after a toll is processed."""
    success: bool
    toll_message: TollMessage
    payer_balance_after: float
    creator_revenue: float
    error: str = ""


class TollSummary(BaseModel):
    """Summary of toll activity for a session/task."""
    session_id: str
    total_messages_metered: int = 0
    total_tolls_usd: float = 0.0
    total_creator_revenue_usd: float = 0.0
    messages_by_type: dict[str, int] = Field(default_factory=dict)


def _generate_api_key() -> str:
    return f"forge_{uuid.uuid4().hex}"


class APIKey(BaseModel):
    """API key for external agent authentication."""
    api_key: str = Field(default_factory=_generate_api_key)
    agent_id: str
    owner_id: str = "anonymous"
    created_at: str = Field(default_factory=_now_iso)
    last_used_at: str | None = None
    is_revoked: bool = False
