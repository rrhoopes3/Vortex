"""
SQLite-backed ledger for the toll protocol.

Thread-safe via a single connection in serialized mode + a reentrant lock.
Designed for future blockchain upgrade via SettlementBackend abstraction.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from forge.toll.models import (
    AgentProfile, APIKey, Invoice, TollMessage, TollReceipt, TollSummary,
    Transaction, Wallet,
)

if TYPE_CHECKING:
    from forge.toll.settlement import SettlementBackend

log = logging.getLogger("forge.toll.ledger")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    wallet_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    agent_id TEXT NOT NULL UNIQUE,
    balance_usd REAL NOT NULL DEFAULT 10.0,
    total_deposited REAL NOT NULL DEFAULT 10.0,
    total_spent REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id TEXT PRIMARY KEY,
    tx_type TEXT NOT NULL CHECK(tx_type IN ('toll','deposit','withdrawal','refund','creator_payout')),
    from_wallet TEXT NOT NULL,
    to_wallet TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    toll_message_id TEXT,
    description TEXT,
    timestamp TEXT NOT NULL,
    settlement_status TEXT NOT NULL DEFAULT 'local',
    chain_tx_hash TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS toll_messages (
    message_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    receiver TEXT NOT NULL,
    message_type TEXT NOT NULL,
    payload_summary TEXT,
    token_count INTEGER DEFAULT 0,
    toll_amount_usd REAL NOT NULL,
    creator_revenue_usd REAL NOT NULL,
    tx_hash TEXT,
    timestamp TEXT NOT NULL,
    session_id TEXT,
    hop_number INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_tx_from ON transactions(from_wallet);
CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_tm_session ON toll_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tm_sender ON toll_messages(sender);

CREATE TABLE IF NOT EXISTS api_keys (
    api_key TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    is_revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ak_agent ON api_keys(agent_id);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','paid','expired')),
    created_at TEXT NOT NULL,
    paid_at TEXT,
    solana_tx_hash TEXT DEFAULT '',
    solana_amount_usdc REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_inv_agent ON invoices(agent_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON invoices(status);

CREATE TABLE IF NOT EXISTS processed_solana_txs (
    signature TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL,
    agent_id TEXT DEFAULT '',
    amount_usdc REAL DEFAULT 0.0,
    invoice_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    capabilities TEXT DEFAULT '[]',
    is_public INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

CREATOR_AGENT_ID = "creator"


class Ledger:
    """SQLite-backed wallet and transaction store."""

    def __init__(self, db_path: Path | str, settlement: SettlementBackend | None = None):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

        if settlement is None:
            from forge.toll.settlement import LocalSettlement
            settlement = LocalSettlement()
        self._settlement = settlement

        self._init_db()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Ensure creator wallet exists
        self._ensure_wallet(CREATOR_AGENT_ID, "creator")
        log.info("Toll ledger initialized: %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Wallets ────────────────────────────────────────────────────────────

    def _ensure_wallet(self, agent_id: str, owner_id: str = "system",
                       initial_balance: float = 0.0) -> Wallet:
        """Create a wallet if it doesn't exist, return it either way."""
        cur = self._conn.execute(
            "SELECT wallet_id, owner_id, agent_id, balance_usd, total_deposited, "
            "total_spent, created_at, is_active FROM wallets WHERE agent_id = ?",
            (agent_id,),
        )
        row = cur.fetchone()
        if row:
            return Wallet(
                wallet_id=row[0], owner_id=row[1], agent_id=row[2],
                balance_usd=row[3], total_deposited=row[4], total_spent=row[5],
                created_at=row[6], is_active=bool(row[7]),
            )
        w = Wallet(agent_id=agent_id, owner_id=owner_id,
                   balance_usd=initial_balance, total_deposited=initial_balance)
        self._conn.execute(
            "INSERT INTO wallets (wallet_id, owner_id, agent_id, balance_usd, "
            "total_deposited, total_spent, created_at, is_active) VALUES (?,?,?,?,?,?,?,?)",
            (w.wallet_id, w.owner_id, w.agent_id, w.balance_usd,
             w.total_deposited, w.total_spent, w.created_at, int(w.is_active)),
        )
        self._conn.commit()
        return w

    def get_or_create_wallet(self, agent_id: str, owner_id: str = "system",
                             initial_balance: float = 10.0) -> Wallet:
        with self._lock:
            return self._ensure_wallet(agent_id, owner_id, initial_balance)

    def get_wallet(self, agent_id: str) -> Wallet | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT wallet_id, owner_id, agent_id, balance_usd, total_deposited, "
                "total_spent, created_at, is_active FROM wallets WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return Wallet(
                wallet_id=row[0], owner_id=row[1], agent_id=row[2],
                balance_usd=row[3], total_deposited=row[4], total_spent=row[5],
                created_at=row[6], is_active=bool(row[7]),
            )

    def get_all_wallets(self) -> list[Wallet]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT wallet_id, owner_id, agent_id, balance_usd, total_deposited, "
                "total_spent, created_at, is_active FROM wallets ORDER BY agent_id",
            )
            return [
                Wallet(wallet_id=r[0], owner_id=r[1], agent_id=r[2],
                       balance_usd=r[3], total_deposited=r[4], total_spent=r[5],
                       created_at=r[6], is_active=bool(r[7]))
                for r in cur.fetchall()
            ]

    def deposit(self, agent_id: str, amount: float) -> Transaction:
        with self._lock:
            w = self._ensure_wallet(agent_id)
            new_balance = w.balance_usd + amount
            self._conn.execute(
                "UPDATE wallets SET balance_usd = ?, total_deposited = total_deposited + ? "
                "WHERE agent_id = ?",
                (new_balance, amount, agent_id),
            )
            tx = Transaction(
                tx_type="deposit", from_wallet="external",
                to_wallet=w.wallet_id, amount_usd=amount,
                description=f"Deposit to {agent_id}",
            )
            self._conn.execute(
                "INSERT INTO transactions (tx_id, tx_type, from_wallet, to_wallet, "
                "amount_usd, toll_message_id, description, timestamp, "
                "settlement_status, chain_tx_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tx.tx_id, tx.tx_type, tx.from_wallet, tx.to_wallet,
                 tx.amount_usd, tx.toll_message_id, tx.description,
                 tx.timestamp, tx.settlement_status, tx.chain_tx_hash),
            )
            self._conn.commit()
            return tx

    # ── Toll Processing ────────────────────────────────────────────────────

    def process_toll(self, toll_msg: TollMessage) -> TollReceipt:
        """Process a toll: deduct from sender, credit creator. Returns receipt."""
        with self._lock:
            # Get or create sender wallet
            sender_w = self._ensure_wallet(toll_msg.sender, initial_balance=10.0)
            creator_w = self._ensure_wallet(CREATOR_AGENT_ID, "creator", initial_balance=0.0)

            toll_amount = toll_msg.toll_amount_usd
            creator_cut = toll_msg.creator_revenue_usd

            # Deficit tracking: deduct even if balance goes negative
            new_sender_balance = sender_w.balance_usd - toll_amount
            new_creator_balance = creator_w.balance_usd + creator_cut

            # Update sender wallet
            self._conn.execute(
                "UPDATE wallets SET balance_usd = ?, total_spent = total_spent + ? "
                "WHERE agent_id = ?",
                (new_sender_balance, toll_amount, toll_msg.sender),
            )

            # Update creator wallet
            self._conn.execute(
                "UPDATE wallets SET balance_usd = ?, total_deposited = total_deposited + ? "
                "WHERE agent_id = ?",
                (new_creator_balance, creator_cut, CREATOR_AGENT_ID),
            )

            # Record transaction
            tx = Transaction(
                tx_type="toll", from_wallet=sender_w.wallet_id,
                to_wallet=creator_w.wallet_id, amount_usd=toll_amount,
                toll_message_id=toll_msg.message_id,
                description=f"Toll: {toll_msg.sender} → {toll_msg.receiver} ({toll_msg.message_type})",
            )
            toll_msg.tx_hash = tx.tx_id

            self._conn.execute(
                "INSERT INTO transactions (tx_id, tx_type, from_wallet, to_wallet, "
                "amount_usd, toll_message_id, description, timestamp, "
                "settlement_status, chain_tx_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tx.tx_id, tx.tx_type, tx.from_wallet, tx.to_wallet,
                 tx.amount_usd, tx.toll_message_id, tx.description,
                 tx.timestamp, tx.settlement_status, tx.chain_tx_hash),
            )

            # Record toll message
            self._conn.execute(
                "INSERT INTO toll_messages (message_id, sender, receiver, message_type, "
                "payload_summary, token_count, toll_amount_usd, creator_revenue_usd, "
                "tx_hash, timestamp, session_id, hop_number) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (toll_msg.message_id, toll_msg.sender, toll_msg.receiver,
                 toll_msg.message_type, toll_msg.payload_summary, toll_msg.token_count,
                 toll_msg.toll_amount_usd, toll_msg.creator_revenue_usd,
                 toll_msg.tx_hash, toll_msg.timestamp, toll_msg.session_id,
                 toll_msg.hop_number),
            )

            self._conn.commit()

            return TollReceipt(
                success=True,
                toll_message=toll_msg,
                payer_balance_after=new_sender_balance,
                creator_revenue=creator_cut,
            )

    # ── Queries ────────────────────────────────────────────────────────────

    def get_balance(self, agent_id: str) -> float:
        w = self.get_wallet(agent_id)
        return w.balance_usd if w else 0.0

    def get_transactions(self, agent_id: str | None = None, limit: int = 50) -> list[Transaction]:
        with self._lock:
            if agent_id:
                w = self._ensure_wallet(agent_id)
                cur = self._conn.execute(
                    "SELECT tx_id, tx_type, from_wallet, to_wallet, amount_usd, "
                    "toll_message_id, description, timestamp, settlement_status, chain_tx_hash "
                    "FROM transactions WHERE from_wallet = ? OR to_wallet = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (w.wallet_id, w.wallet_id, limit),
                )
            else:
                cur = self._conn.execute(
                    "SELECT tx_id, tx_type, from_wallet, to_wallet, amount_usd, "
                    "toll_message_id, description, timestamp, settlement_status, chain_tx_hash "
                    "FROM transactions ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [
                Transaction(
                    tx_id=r[0], tx_type=r[1], from_wallet=r[2], to_wallet=r[3],
                    amount_usd=r[4], toll_message_id=r[5] or "", description=r[6] or "",
                    timestamp=r[7], settlement_status=r[8], chain_tx_hash=r[9] or "",
                )
                for r in cur.fetchall()
            ]

    def get_session_summary(self, session_id: str) -> TollSummary:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(toll_amount_usd), 0), "
                "COALESCE(SUM(creator_revenue_usd), 0) "
                "FROM toll_messages WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            total_messages = row[0]
            total_tolls = row[1]
            total_creator = row[2]

            # Messages by type
            cur2 = self._conn.execute(
                "SELECT message_type, COUNT(*) FROM toll_messages "
                "WHERE session_id = ? GROUP BY message_type",
                (session_id,),
            )
            by_type = {r[0]: r[1] for r in cur2.fetchall()}

            return TollSummary(
                session_id=session_id,
                total_messages_metered=total_messages,
                total_tolls_usd=round(total_tolls, 8),
                total_creator_revenue_usd=round(total_creator, 8),
                messages_by_type=by_type,
            )

    def get_creator_revenue(self) -> float:
        w = self.get_wallet(CREATOR_AGENT_ID)
        return w.balance_usd if w else 0.0

    def get_revenue_by_session(self, limit: int = 20) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT session_id, COUNT(*), SUM(toll_amount_usd), SUM(creator_revenue_usd) "
                "FROM toll_messages WHERE session_id != '' "
                "GROUP BY session_id ORDER BY MAX(timestamp) DESC LIMIT ?",
                (limit,),
            )
            return [
                {
                    "session_id": r[0],
                    "message_count": r[1],
                    "total_tolls_usd": round(r[2], 8),
                    "creator_revenue_usd": round(r[3], 8),
                }
                for r in cur.fetchall()
            ]

    # ── Settlement (Beat 3 hooks) ──────────────────────────────────────────

    def export_for_settlement(self, since: str = "") -> list[Transaction]:
        """Export unsettled (local) transactions for blockchain settlement."""
        with self._lock:
            query = ("SELECT tx_id, tx_type, from_wallet, to_wallet, amount_usd, "
                     "toll_message_id, description, timestamp, settlement_status, chain_tx_hash "
                     "FROM transactions WHERE settlement_status = 'local'")
            params: tuple = ()
            if since:
                query += " AND timestamp > ?"
                params = (since,)
            query += " ORDER BY timestamp"
            cur = self._conn.execute(query, params)
            return [
                Transaction(
                    tx_id=r[0], tx_type=r[1], from_wallet=r[2], to_wallet=r[3],
                    amount_usd=r[4], toll_message_id=r[5] or "", description=r[6] or "",
                    timestamp=r[7], settlement_status=r[8], chain_tx_hash=r[9] or "",
                )
                for r in cur.fetchall()
            ]

    def mark_settled(self, tx_ids: list[str], chain_hash: str) -> None:
        """Mark transactions as settled on-chain."""
        with self._lock:
            placeholders = ",".join("?" for _ in tx_ids)
            self._conn.execute(
                f"UPDATE transactions SET settlement_status = 'settled_chain', "
                f"chain_tx_hash = ? WHERE tx_id IN ({placeholders})",
                [chain_hash] + tx_ids,
            )
            self._conn.commit()

    # ── API Keys ───────────────────────────────────────────────────────────

    def create_api_key(self, agent_id: str, owner_id: str = "anonymous") -> APIKey:
        """Generate and store a new API key for an agent."""
        key = APIKey(agent_id=agent_id, owner_id=owner_id)
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_keys (api_key, agent_id, owner_id, created_at, "
                "last_used_at, is_revoked) VALUES (?,?,?,?,?,?)",
                (key.api_key, key.agent_id, key.owner_id, key.created_at,
                 key.last_used_at, int(key.is_revoked)),
            )
            self._conn.commit()
        return key

    def validate_api_key(self, api_key: str) -> APIKey | None:
        """Validate an API key. Returns the key record if valid, None otherwise.
        Updates last_used_at on success."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT api_key, agent_id, owner_id, created_at, last_used_at, is_revoked "
                "FROM api_keys WHERE api_key = ?",
                (api_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row[5]:  # is_revoked
                return None
            # Update last_used_at
            from forge.toll.models import _now_iso
            now = _now_iso()
            self._conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE api_key = ?",
                (now, api_key),
            )
            self._conn.commit()
            return APIKey(
                api_key=row[0], agent_id=row[1], owner_id=row[2],
                created_at=row[3], last_used_at=now, is_revoked=False,
            )

    def revoke_api_key(self, api_key: str) -> bool:
        """Revoke an API key. Returns True if found and revoked."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE api_keys SET is_revoked = 1 WHERE api_key = ? AND is_revoked = 0",
                (api_key,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_api_keys(self, agent_id: str) -> list[APIKey]:
        """Get all API keys for an agent."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT api_key, agent_id, owner_id, created_at, last_used_at, is_revoked "
                "FROM api_keys WHERE agent_id = ? ORDER BY created_at DESC",
                (agent_id,),
            )
            return [
                APIKey(api_key=r[0], agent_id=r[1], owner_id=r[2],
                       created_at=r[3], last_used_at=r[4], is_revoked=bool(r[5]))
                for r in cur.fetchall()
            ]

    # ── Invoices (Beat 4) ─────────────────────────────────────────────────

    def create_invoice(self, agent_id: str, amount_usd: float) -> Invoice:
        """Create a pending invoice for an agent (used in 402 responses)."""
        inv = Invoice(agent_id=agent_id, amount_usd=amount_usd)
        with self._lock:
            self._conn.execute(
                "INSERT INTO invoices (invoice_id, agent_id, amount_usd, status, "
                "created_at, paid_at, solana_tx_hash, solana_amount_usdc) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (inv.invoice_id, inv.agent_id, inv.amount_usd, inv.status,
                 inv.created_at, inv.paid_at, inv.solana_tx_hash, inv.solana_amount_usdc),
            )
            self._conn.commit()
        return inv

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        """Look up an invoice by ID."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT invoice_id, agent_id, amount_usd, status, created_at, "
                "paid_at, solana_tx_hash, solana_amount_usdc FROM invoices WHERE invoice_id = ?",
                (invoice_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return Invoice(
                invoice_id=row[0], agent_id=row[1], amount_usd=row[2],
                status=row[3], created_at=row[4], paid_at=row[5],
                solana_tx_hash=row[6] or "", solana_amount_usdc=row[7] or 0.0,
            )

    def mark_invoice_paid(self, invoice_id: str, solana_tx_hash: str,
                          solana_amount_usdc: float) -> bool:
        """Mark an invoice as paid with the Solana transaction details."""
        from forge.toll.models import _now_iso
        with self._lock:
            cur = self._conn.execute(
                "UPDATE invoices SET status = 'paid', paid_at = ?, "
                "solana_tx_hash = ?, solana_amount_usdc = ? "
                "WHERE invoice_id = ? AND status = 'pending'",
                (_now_iso(), solana_tx_hash, solana_amount_usdc, invoice_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ── Solana TX Tracking (Beat 4) ────────────────────────────────────────

    def is_solana_tx_processed(self, signature: str) -> bool:
        """Check if a Solana transaction has already been processed (idempotency)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM processed_solana_txs WHERE signature = ?",
                (signature,),
            )
            return cur.fetchone() is not None

    def record_solana_tx(self, signature: str, agent_id: str = "",
                         amount_usdc: float = 0.0, invoice_id: str = "") -> None:
        """Record a processed Solana transaction to prevent double-crediting."""
        from forge.toll.models import _now_iso
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO processed_solana_txs "
                "(signature, processed_at, agent_id, amount_usdc, invoice_id) "
                "VALUES (?,?,?,?,?)",
                (signature, _now_iso(), agent_id, amount_usdc, invoice_id),
            )
            self._conn.commit()

    # ── Agent Profiles (Beat 5) ──────────────────────────────────────────

    def create_agent_profile(self, agent_id: str, name: str,
                             description: str = "",
                             capabilities: list[str] | None = None) -> AgentProfile:
        """Create or update an agent profile."""
        import json as _json
        caps = capabilities or []
        profile = AgentProfile(agent_id=agent_id, name=name,
                               description=description, capabilities=caps)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_profiles "
                "(agent_id, name, description, capabilities, is_public, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (profile.agent_id, profile.name, profile.description,
                 _json.dumps(profile.capabilities), int(profile.is_public),
                 profile.created_at),
            )
            self._conn.commit()
        return profile

    def get_agent_profile(self, agent_id: str) -> AgentProfile | None:
        """Get a single agent profile."""
        import json as _json
        with self._lock:
            cur = self._conn.execute(
                "SELECT agent_id, name, description, capabilities, is_public, created_at "
                "FROM agent_profiles WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return AgentProfile(
                agent_id=row[0], name=row[1], description=row[2],
                capabilities=_json.loads(row[3] or "[]"),
                is_public=bool(row[4]), created_at=row[5],
            )

    def list_agent_profiles(self, public_only: bool = True) -> list[AgentProfile]:
        """List all agent profiles (optionally filtered to public)."""
        import json as _json
        with self._lock:
            query = "SELECT agent_id, name, description, capabilities, is_public, created_at FROM agent_profiles"
            if public_only:
                query += " WHERE is_public = 1"
            query += " ORDER BY name"
            cur = self._conn.execute(query)
            return [
                AgentProfile(
                    agent_id=r[0], name=r[1], description=r[2],
                    capabilities=_json.loads(r[3] or "[]"),
                    is_public=bool(r[4]), created_at=r[5],
                )
                for r in cur.fetchall()
            ]

    def update_agent_profile(self, agent_id: str, description: str | None = None,
                             capabilities: list[str] | None = None,
                             is_public: bool | None = None) -> AgentProfile | None:
        """Update an existing agent profile. Returns updated profile or None."""
        import json as _json
        with self._lock:
            cur = self._conn.execute(
                "SELECT agent_id, name, description, capabilities, is_public, created_at "
                "FROM agent_profiles WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            new_desc = description if description is not None else row[2]
            new_caps = _json.dumps(capabilities) if capabilities is not None else row[3]
            new_public = int(is_public) if is_public is not None else row[4]
            self._conn.execute(
                "UPDATE agent_profiles SET description = ?, capabilities = ?, is_public = ? "
                "WHERE agent_id = ?",
                (new_desc, new_caps, new_public, agent_id),
            )
            self._conn.commit()
            return AgentProfile(
                agent_id=row[0], name=row[1], description=new_desc,
                capabilities=_json.loads(new_caps) if isinstance(new_caps, str) else new_caps,
                is_public=bool(new_public), created_at=row[5],
            )

    # ── Admin ──────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all toll data (dev/testing)."""
        with self._lock:
            self._conn.executescript("""
                DELETE FROM agent_profiles;
                DELETE FROM processed_solana_txs;
                DELETE FROM invoices;
                DELETE FROM api_keys;
                DELETE FROM toll_messages;
                DELETE FROM transactions;
                DELETE FROM wallets;
            """)
            self._conn.commit()
            self._ensure_wallet(CREATOR_AGENT_ID, "creator", initial_balance=0.0)
            log.info("Toll ledger reset")
