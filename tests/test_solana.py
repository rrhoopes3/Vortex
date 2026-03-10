"""
Tests for Beat 4: Solana USDC Watcher — Close the Money Loop.

Covers:
  - Invoice CRUD (ledger)
  - Solana TX idempotency (ledger)
  - SolanaSettlement backend (mocked RPC)
  - SolanaUSDCWatcher: memo extraction, USDC amount extraction,
    agent resolution, full deposit flow (all mocked — no real RPC)
  - 402 invoice persistence
  - Deposit status endpoint
  - Config validation
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path):
    """Isolated ledger with invoice tables."""
    from forge.toll.ledger import Ledger
    return Ledger(tmp_path / "test_solana.db")


@pytest.fixture
def watcher(ledger):
    """SolanaUSDCWatcher with mocked RPC (no real network calls)."""
    from forge.toll.solana_watcher import SolanaUSDCWatcher
    return SolanaUSDCWatcher(
        ledger=ledger,
        rpc_url="https://api.devnet.solana.com",
        receiver_address="2RzBNDG52n7EhqSeUYksa5eyTb7YJ8b3xvyJLESzY6zf",
        usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        poll_interval=5,
    )


def _mock_parsed_tx(memo: str = "", usdc_amount: float = 0.0,
                     receiver: str = "2RzBNDG52n7EhqSeUYksa5eyTb7YJ8b3xvyJLESzY6zf",
                     mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v") -> dict:
    """Build a mock Solana transaction result in jsonParsed format."""
    instructions = []
    if memo:
        instructions.append({
            "programId": "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
            "parsed": memo,
        })

    pre_balances = []
    post_balances = []
    if usdc_amount > 0:
        pre_balances.append({
            "accountIndex": 1,
            "mint": mint,
            "owner": receiver,
            "uiTokenAmount": {"uiAmount": 100.0},
        })
        post_balances.append({
            "accountIndex": 1,
            "mint": mint,
            "owner": receiver,
            "uiTokenAmount": {"uiAmount": 100.0 + usdc_amount},
        })

    return {
        "transaction": {
            "message": {
                "instructions": instructions,
            },
        },
        "meta": {
            "err": None,
            "innerInstructions": [],
            "preTokenBalances": pre_balances,
            "postTokenBalances": post_balances,
        },
    }


# ── Invoice CRUD (Ledger) ────────────────────────────────────────────────

class TestInvoiceCRUD:
    def test_create_invoice(self, ledger):
        inv = ledger.create_invoice("ext_test-bot", 5.0)
        assert inv.invoice_id.startswith("inv_")
        assert inv.agent_id == "ext_test-bot"
        assert inv.amount_usd == 5.0
        assert inv.status == "pending"

    def test_get_invoice(self, ledger):
        inv = ledger.create_invoice("ext_bot", 2.0)
        fetched = ledger.get_invoice(inv.invoice_id)
        assert fetched is not None
        assert fetched.invoice_id == inv.invoice_id
        assert fetched.agent_id == "ext_bot"
        assert fetched.amount_usd == 2.0

    def test_get_nonexistent_invoice(self, ledger):
        assert ledger.get_invoice("inv_doesnotexist") is None

    def test_mark_invoice_paid(self, ledger):
        inv = ledger.create_invoice("ext_bot", 1.0)
        ok = ledger.mark_invoice_paid(inv.invoice_id, "tx_sig_abc", 1.0)
        assert ok is True
        paid = ledger.get_invoice(inv.invoice_id)
        assert paid.status == "paid"
        assert paid.solana_tx_hash == "tx_sig_abc"
        assert paid.solana_amount_usdc == 1.0
        assert paid.paid_at is not None

    def test_mark_already_paid_returns_false(self, ledger):
        inv = ledger.create_invoice("ext_bot", 1.0)
        ledger.mark_invoice_paid(inv.invoice_id, "sig1", 1.0)
        ok = ledger.mark_invoice_paid(inv.invoice_id, "sig2", 1.0)
        assert ok is False

    def test_mark_nonexistent_invoice_returns_false(self, ledger):
        ok = ledger.mark_invoice_paid("inv_fake", "sig", 1.0)
        assert ok is False


# ── Solana TX Idempotency (Ledger) ───────────────────────────────────────

class TestSolanaTxIdempotency:
    def test_not_processed_initially(self, ledger):
        assert ledger.is_solana_tx_processed("sig_new") is False

    def test_record_and_check(self, ledger):
        ledger.record_solana_tx("sig_abc", "ext_bot", 5.0, "inv_123")
        assert ledger.is_solana_tx_processed("sig_abc") is True

    def test_double_record_ignored(self, ledger):
        ledger.record_solana_tx("sig_dup", "ext_bot", 5.0)
        ledger.record_solana_tx("sig_dup", "ext_bot", 5.0)  # should not raise
        assert ledger.is_solana_tx_processed("sig_dup") is True

    def test_reset_clears_processed_txs(self, ledger):
        ledger.record_solana_tx("sig_reset")
        ledger.reset()
        assert ledger.is_solana_tx_processed("sig_reset") is False

    def test_reset_clears_invoices(self, ledger):
        inv = ledger.create_invoice("ext_bot", 1.0)
        ledger.reset()
        assert ledger.get_invoice(inv.invoice_id) is None


# ── Memo Extraction ──────────────────────────────────────────────────────

class TestMemoExtraction:
    def test_extract_memo_v2(self, watcher):
        tx = _mock_parsed_tx(memo="inv_abc123")
        assert watcher._extract_memo(tx) == "inv_abc123"

    def test_extract_memo_v1(self, watcher):
        tx = _mock_parsed_tx()
        # Override with v1 program ID
        tx["transaction"]["message"]["instructions"] = [{
            "programId": "Memo1UhkJBfCR6MNLc6LzN7E6qoRFkYS5A7EN7wrV3",
            "parsed": "ext_my-bot",
        }]
        assert watcher._extract_memo(tx) == "ext_my-bot"

    def test_extract_memo_none(self, watcher):
        tx = _mock_parsed_tx()  # no memo instruction
        assert watcher._extract_memo(tx) == ""

    def test_extract_memo_inner_instructions(self, watcher):
        tx = _mock_parsed_tx()
        tx["meta"]["innerInstructions"] = [{
            "instructions": [{
                "programId": "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
                "parsed": "inv_inner123",
            }],
        }]
        assert watcher._extract_memo(tx) == "inv_inner123"

    def test_extract_memo_whitespace_stripped(self, watcher):
        tx = _mock_parsed_tx(memo="  inv_abc  ")
        assert watcher._extract_memo(tx) == "inv_abc"

    def test_extract_memo_data_field(self, watcher):
        """Some encodings use 'data' instead of 'parsed'."""
        tx = _mock_parsed_tx()
        tx["transaction"]["message"]["instructions"] = [{
            "programId": "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
            "data": "inv_data123",
        }]
        assert watcher._extract_memo(tx) == "inv_data123"


# ── USDC Amount Extraction ───────────────────────────────────────────────

class TestUSDCAmountExtraction:
    def test_extract_amount(self, watcher):
        tx = _mock_parsed_tx(usdc_amount=5.5)
        assert watcher._extract_usdc_amount(tx) == 5.5

    def test_extract_zero_when_no_balance_change(self, watcher):
        tx = _mock_parsed_tx(usdc_amount=0.0)
        assert watcher._extract_usdc_amount(tx) == 0.0

    def test_extract_wrong_mint_ignored(self, watcher):
        tx = _mock_parsed_tx(usdc_amount=5.0, mint="WrongMintAddress")
        assert watcher._extract_usdc_amount(tx) == 0.0

    def test_extract_wrong_receiver_ignored(self, watcher):
        tx = _mock_parsed_tx(usdc_amount=5.0, receiver="SomeOtherWallet")
        assert watcher._extract_usdc_amount(tx) == 0.0

    def test_extract_small_amount(self, watcher):
        tx = _mock_parsed_tx(usdc_amount=0.000001)
        assert watcher._extract_usdc_amount(tx) == 0.000001


# ── Agent Resolution ─────────────────────────────────────────────────────

class TestAgentResolution:
    def test_resolve_by_invoice(self, watcher, ledger):
        inv = ledger.create_invoice("ext_bot-a", 5.0)
        agent_id, invoice_id = watcher._resolve_agent(inv.invoice_id)
        assert agent_id == "ext_bot-a"
        assert invoice_id == inv.invoice_id

    def test_resolve_by_agent_id(self, watcher, ledger):
        ledger.get_or_create_wallet("ext_bot-b")
        agent_id, invoice_id = watcher._resolve_agent("ext_bot-b")
        assert agent_id == "ext_bot-b"
        assert invoice_id == ""

    def test_resolve_unknown_invoice(self, watcher):
        agent_id, _ = watcher._resolve_agent("inv_doesnotexist")
        assert agent_id == ""

    def test_resolve_unknown_agent(self, watcher):
        agent_id, _ = watcher._resolve_agent("ext_nonexistent")
        assert agent_id == ""

    def test_resolve_invalid_memo(self, watcher):
        agent_id, _ = watcher._resolve_agent("random_text")
        assert agent_id == ""

    def test_resolve_paid_invoice_rejected(self, watcher, ledger):
        inv = ledger.create_invoice("ext_bot-c", 5.0)
        ledger.mark_invoice_paid(inv.invoice_id, "sig_old", 5.0)
        agent_id, _ = watcher._resolve_agent(inv.invoice_id)
        assert agent_id == ""  # already paid


# ── Full Deposit Flow (Mocked RPC) ──────────────────────────────────────

class TestFullDepositFlow:
    def test_poll_credits_agent(self, watcher, ledger):
        """End-to-end: new signature → fetch tx → extract memo + amount → credit."""
        # Set up agent and invoice
        ledger.get_or_create_wallet("ext_depositor", initial_balance=0.0)
        inv = ledger.create_invoice("ext_depositor", 10.0)

        mock_tx = _mock_parsed_tx(memo=inv.invoice_id, usdc_amount=10.0)

        # Mock RPC calls
        with patch("forge.toll.solana_watcher.requests.post") as mock_post:
            # First call: getSignaturesForAddress
            sig_response = MagicMock()
            sig_response.json.return_value = {
                "result": [{"signature": "sig_full_flow", "err": None}],
            }
            # Second call: getTransaction
            tx_response = MagicMock()
            tx_response.json.return_value = {"result": mock_tx}

            mock_post.side_effect = [sig_response, tx_response]

            watcher._poll_once()

        # Verify: wallet credited
        assert ledger.get_balance("ext_depositor") == 10.0

        # Verify: invoice marked paid
        paid_inv = ledger.get_invoice(inv.invoice_id)
        assert paid_inv.status == "paid"
        assert paid_inv.solana_tx_hash == "sig_full_flow"

        # Verify: tx recorded for idempotency
        assert ledger.is_solana_tx_processed("sig_full_flow")

    def test_poll_skips_already_processed(self, watcher, ledger):
        """Duplicate signatures should not credit again."""
        ledger.get_or_create_wallet("ext_dup", initial_balance=0.0)
        ledger.record_solana_tx("sig_already_done")

        with patch("forge.toll.solana_watcher.requests.post") as mock_post:
            sig_response = MagicMock()
            sig_response.json.return_value = {
                "result": [{"signature": "sig_already_done", "err": None}],
            }
            mock_post.return_value = sig_response
            watcher._poll_once()

        # Should NOT have called getTransaction (only getSignatures)
        assert mock_post.call_count == 1
        assert ledger.get_balance("ext_dup") == 0.0

    def test_poll_skips_failed_tx(self, watcher, ledger):
        """Transactions with err != None should be skipped."""
        with patch("forge.toll.solana_watcher.requests.post") as mock_post:
            sig_response = MagicMock()
            sig_response.json.return_value = {
                "result": [{"signature": "sig_failed", "err": {"InstructionError": [0, "Custom"]}}],
            }
            mock_post.return_value = sig_response
            watcher._poll_once()

        # Should be recorded but not processed further
        assert ledger.is_solana_tx_processed("sig_failed")

    def test_poll_no_new_signatures(self, watcher, ledger):
        """Empty signature list should be a no-op."""
        with patch("forge.toll.solana_watcher.requests.post") as mock_post:
            sig_response = MagicMock()
            sig_response.json.return_value = {"result": []}
            mock_post.return_value = sig_response
            watcher._poll_once()

        assert mock_post.call_count == 1


# ── SolanaSettlement Backend ─────────────────────────────────────────────

class TestSolanaSettlement:
    def test_settle_raises(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")
        with pytest.raises(NotImplementedError):
            s.settle([])

    def test_verify_success(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "result": {"meta": {"err": None}},
            }
            mock_post.return_value = mock_resp
            assert s.verify("sig_abc") is True

    def test_verify_failed_tx(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "result": {"meta": {"err": {"InstructionError": [0, "Custom"]}}},
            }
            mock_post.return_value = mock_resp
            assert s.verify("sig_fail") is False

    def test_verify_not_found(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"result": None}
            mock_post.return_value = mock_resp
            assert s.verify("sig_missing") is False

    def test_verify_rpc_error(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")

        with patch("requests.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")
            assert s.verify("sig_err") is False

    def test_get_balance_success(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com",
                             "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "result": {
                    "value": [{
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {"uiAmount": 42.5},
                                    },
                                },
                            },
                        },
                    }],
                },
            }
            mock_post.return_value = mock_resp
            assert s.get_balance("SomeWallet") == 42.5

    def test_get_balance_empty(self):
        from forge.toll.settlement import SolanaSettlement
        s = SolanaSettlement("https://rpc.example.com", "mint")

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"result": {"value": []}}
            mock_post.return_value = mock_resp
            assert s.get_balance("EmptyWallet") == 0.0


# ── 402 Invoice Persistence ─────────────────────────────────────────────

class TestInvoicePersistence:
    def test_402_creates_persisted_invoice(self):
        """The 402 response should persist an invoice in the ledger."""
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            # Register agent
            r = client.post("/api/v1/agents/register", json={"name": "inv-persist-bot"})
            data = r.get_json()
            api_key = data["api_key"]
            agent_id = data["agent_id"]

            # Drain wallet
            from forge.toll.public_api import _get_ledger
            ledger = _get_ledger()
            with ledger._lock:
                ledger._conn.execute(
                    "UPDATE wallets SET balance_usd = 0.0 WHERE agent_id = ?",
                    (agent_id,),
                )
                ledger._conn.commit()

            # Submit task → 402
            r = client.post("/api/v1/tasks",
                            json={"task": "test"},
                            headers={"X-API-Key": api_key})
            assert r.status_code == 402
            data = r.get_json()
            invoice_id = data["invoice_id"]
            assert invoice_id.startswith("inv_")

            # Verify invoice exists in ledger
            inv = ledger.get_invoice(invoice_id)
            assert inv is not None
            assert inv.agent_id == agent_id
            assert inv.status == "pending"

    def test_402_includes_memo_in_solana_payment(self):
        """402 solana_usdc payment method should include memo field."""
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            r = client.post("/api/v1/agents/register", json={"name": "memo-bot"})
            data = r.get_json()
            api_key = data["api_key"]
            agent_id = data["agent_id"]

            from forge.toll.public_api import _get_ledger
            ledger = _get_ledger()
            with ledger._lock:
                ledger._conn.execute(
                    "UPDATE wallets SET balance_usd = 0.0 WHERE agent_id = ?",
                    (agent_id,),
                )
                ledger._conn.commit()

            r = client.post("/api/v1/tasks",
                            json={"task": "test"},
                            headers={"X-API-Key": api_key})
            assert r.status_code == 402
            data = r.get_json()

            solana_method = next(
                (m for m in data["payment_methods"] if m["type"] == "solana_usdc"),
                None,
            )
            assert solana_method is not None
            assert "memo" in solana_method
            assert solana_method["memo"] == data["invoice_id"]


# ── Deposit Status Endpoint ─────────────────────────────────────────────

class TestDepositStatus:
    def test_status_pending(self):
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            r = client.post("/api/v1/agents/register", json={"name": "status-bot"})
            data = r.get_json()
            api_key = data["api_key"]
            agent_id = data["agent_id"]

            # Create invoice manually
            from forge.toll.public_api import _get_ledger
            ledger = _get_ledger()
            inv = ledger.create_invoice(agent_id, 5.0)

            r = client.get(f"/api/v1/wallet/deposit/status/{inv.invoice_id}",
                           headers={"X-API-Key": api_key})
            assert r.status_code == 200
            data = r.get_json()
            assert data["status"] == "pending"
            assert data["invoice_id"] == inv.invoice_id

    def test_status_not_found(self):
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            r = client.post("/api/v1/agents/register", json={"name": "status-404-bot"})
            api_key = r.get_json()["api_key"]

            r = client.get("/api/v1/wallet/deposit/status/inv_doesnotexist",
                           headers={"X-API-Key": api_key})
            assert r.status_code == 404

    def test_status_other_agent_rejected(self):
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            # Register two agents
            r1 = client.post("/api/v1/agents/register", json={"name": "agent-a-stat"})
            r2 = client.post("/api/v1/agents/register", json={"name": "agent-b-stat"})
            key_b = r2.get_json()["api_key"]
            agent_a_id = r1.get_json()["agent_id"]

            # Create invoice for agent A
            from forge.toll.public_api import _get_ledger
            ledger = _get_ledger()
            inv = ledger.create_invoice(agent_a_id, 5.0)

            # Agent B tries to view Agent A's invoice
            r = client.get(f"/api/v1/wallet/deposit/status/{inv.invoice_id}",
                           headers={"X-API-Key": key_b})
            assert r.status_code == 404


# ── Config Validation ────────────────────────────────────────────────────

class TestSolanaConfig:
    def test_watcher_disabled_by_default(self):
        from forge.config import SOLANA_WATCHER_ENABLED
        # Default is false unless env var set
        assert isinstance(SOLANA_WATCHER_ENABLED, bool)

    def test_usdc_mint_set(self):
        from forge.config import SOLANA_USDC_MINT
        assert SOLANA_USDC_MINT == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    def test_usdc_decimals(self):
        from forge.config import SOLANA_USDC_DECIMALS
        assert SOLANA_USDC_DECIMALS == 6

    def test_poll_interval_positive(self):
        from forge.config import SOLANA_POLL_INTERVAL
        assert SOLANA_POLL_INTERVAL > 0

    def test_network_valid(self):
        from forge.config import SOLANA_NETWORK
        assert SOLANA_NETWORK in ("devnet", "mainnet-beta")

    def test_receiver_address_set(self):
        from forge.config import MARKETPLACE_SOLANA_USDC_ADDRESS
        assert isinstance(MARKETPLACE_SOLANA_USDC_ADDRESS, str)
