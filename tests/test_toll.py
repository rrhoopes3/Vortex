"""
Tests for the Bot Communication Toll Protocol (Beat 2).
"""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test_toll.db"


@pytest.fixture
def ledger(tmp_db):
    from forge.toll.ledger import Ledger
    led = Ledger(tmp_db)
    yield led
    led.close()


@pytest.fixture
def rate_engine():
    from forge.toll.rates import RateEngine
    return RateEngine()


@pytest.fixture
def relay(ledger, rate_engine):
    from forge.toll.relay import TollRelay
    return TollRelay(ledger, rate_engine)


@pytest.fixture
def client():
    """Flask test client."""
    from forge.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Toll Models ───────────────────────────────────────────────────────────

class TestTollModels:
    def test_toll_message_defaults(self):
        from forge.toll.models import TollMessage
        msg = TollMessage(sender="a", receiver="b", message_type="test")
        assert msg.message_id  # auto-generated
        assert msg.timestamp  # auto-generated
        assert msg.toll_amount_usd == 0.0

    def test_wallet_defaults(self):
        from forge.toll.models import Wallet
        w = Wallet(agent_id="test_agent")
        assert w.wallet_id  # auto-generated
        assert w.balance_usd == 10.0
        assert w.is_active is True

    def test_toll_rate_defaults(self):
        from forge.toll.models import TollRate
        rate = TollRate(message_type="test", base_rate_usd=0.001)
        assert rate.creator_rake_pct == 30.0
        assert rate.volume_discount_threshold == 100

    def test_transaction_defaults(self):
        from forge.toll.models import Transaction
        tx = Transaction(from_wallet="a", to_wallet="b", amount_usd=0.01)
        assert tx.tx_type == "toll"
        assert tx.settlement_status == "local"
        assert tx.chain_tx_hash == ""

    def test_toll_receipt(self):
        from forge.toll.models import TollMessage, TollReceipt
        msg = TollMessage(sender="a", receiver="b", message_type="test")
        receipt = TollReceipt(
            success=True, toll_message=msg,
            payer_balance_after=9.99, creator_revenue=0.003,
        )
        assert receipt.success
        assert receipt.error == ""


# ── Ledger ────────────────────────────────────────────────────────────────

class TestLedger:
    def test_create_wallet(self, ledger):
        w = ledger.get_or_create_wallet("agent_1")
        assert w.agent_id == "agent_1"
        assert w.balance_usd == 10.0

    def test_get_or_create_idempotent(self, ledger):
        w1 = ledger.get_or_create_wallet("agent_1")
        w2 = ledger.get_or_create_wallet("agent_1")
        assert w1.wallet_id == w2.wallet_id

    def test_deposit(self, ledger):
        ledger.get_or_create_wallet("agent_1")
        tx = ledger.deposit("agent_1", 5.0)
        assert tx.tx_type == "deposit"
        assert tx.amount_usd == 5.0
        assert ledger.get_balance("agent_1") == 15.0

    def test_process_toll_deducts_balance(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        msg = TollMessage(
            sender="sender_1", receiver="receiver_1",
            message_type="test", toll_amount_usd=0.01,
            creator_revenue_usd=0.003, session_id="s1",
        )
        receipt = ledger.process_toll(msg)
        assert receipt.success
        assert receipt.payer_balance_after == pytest.approx(9.99)

    def test_process_toll_credits_creator(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        msg = TollMessage(
            sender="sender_1", receiver="receiver_1",
            message_type="test", toll_amount_usd=0.01,
            creator_revenue_usd=0.003, session_id="s1",
        )
        ledger.process_toll(msg)
        assert ledger.get_creator_revenue() == pytest.approx(0.003)

    def test_process_toll_deficit_tracking(self, ledger):
        """Balance goes negative — deficit tracked, not hard stop."""
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("broke_agent", initial_balance=0.001)
        msg = TollMessage(
            sender="broke_agent", receiver="receiver_1",
            message_type="test", toll_amount_usd=0.01,
            creator_revenue_usd=0.003, session_id="s1",
        )
        receipt = ledger.process_toll(msg)
        assert receipt.success  # no hard stop
        assert receipt.payer_balance_after < 0

    def test_transaction_history(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        for i in range(3):
            msg = TollMessage(
                sender="sender_1", receiver="receiver_1",
                message_type="test", toll_amount_usd=0.01,
                creator_revenue_usd=0.003, session_id="s1",
            )
            ledger.process_toll(msg)
        txs = ledger.get_transactions("sender_1")
        assert len(txs) == 3

    def test_session_summary(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        for i in range(5):
            msg = TollMessage(
                sender="sender_1", receiver="receiver_1",
                message_type="test", toll_amount_usd=0.002,
                creator_revenue_usd=0.0006, session_id="session_x",
            )
            ledger.process_toll(msg)
        summary = ledger.get_session_summary("session_x")
        assert summary.total_messages_metered == 5
        assert summary.total_tolls_usd == pytest.approx(0.01)
        assert summary.total_creator_revenue_usd == pytest.approx(0.003)

    def test_get_all_wallets(self, ledger):
        ledger.get_or_create_wallet("a1")
        ledger.get_or_create_wallet("a2")
        wallets = ledger.get_all_wallets()
        agent_ids = [w.agent_id for w in wallets]
        assert "a1" in agent_ids
        assert "a2" in agent_ids
        assert "creator" in agent_ids  # auto-created

    def test_export_for_settlement(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        msg = TollMessage(
            sender="sender_1", receiver="receiver_1",
            message_type="test", toll_amount_usd=0.01,
            creator_revenue_usd=0.003, session_id="s1",
        )
        ledger.process_toll(msg)
        exports = ledger.export_for_settlement()
        assert len(exports) >= 1
        assert exports[0].settlement_status == "local"

    def test_mark_settled(self, ledger):
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("sender_1", initial_balance=10.0)
        msg = TollMessage(
            sender="sender_1", receiver="receiver_1",
            message_type="test", toll_amount_usd=0.01,
            creator_revenue_usd=0.003, session_id="s1",
        )
        ledger.process_toll(msg)
        exports = ledger.export_for_settlement()
        tx_ids = [tx.tx_id for tx in exports]
        ledger.mark_settled(tx_ids, "0xdeadbeef")
        remaining = ledger.export_for_settlement()
        assert len(remaining) == 0

    def test_reset(self, ledger):
        ledger.get_or_create_wallet("agent_1")
        ledger.reset()
        w = ledger.get_wallet("agent_1")
        assert w is None

    def test_thread_safety(self, ledger):
        """Concurrent toll processing doesn't corrupt state."""
        from forge.toll.models import TollMessage
        ledger.get_or_create_wallet("concurrent_sender", initial_balance=100.0)
        errors = []

        def process_tolls():
            try:
                for _ in range(20):
                    msg = TollMessage(
                        sender="concurrent_sender", receiver="receiver",
                        message_type="test", toll_amount_usd=0.001,
                        creator_revenue_usd=0.0003, session_id="concurrent",
                    )
                    ledger.process_toll(msg)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=process_tolls) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 4 threads * 20 tolls = 80 total
        summary = ledger.get_session_summary("concurrent")
        assert summary.total_messages_metered == 80


# ── Rate Engine ───────────────────────────────────────────────────────────

class TestRateEngine:
    def test_default_rates_loaded(self, rate_engine):
        assert rate_engine.get_rate("plan_request") is not None
        assert rate_engine.get_rate("llm_response") is not None
        assert rate_engine.get_rate("tool_invocation") is not None

    def test_calculate_base_rate(self, rate_engine):
        rate = rate_engine.get_rate("plan_request")
        result = rate_engine.calculate(rate, token_count=0)
        assert result == pytest.approx(0.001)

    def test_calculate_with_tokens(self, rate_engine):
        rate = rate_engine.get_rate("llm_response")
        result = rate_engine.calculate(rate, token_count=1000)
        # base (0.0005) + 1000 * 0.000002 = 0.0025
        assert result == pytest.approx(0.0025)

    def test_free_message_types(self, rate_engine):
        rate = rate_engine.get_rate("status_update")
        assert rate.base_rate_usd == 0.0
        rate2 = rate_engine.get_rate("token_usage")
        assert rate2.base_rate_usd == 0.0

    def test_custom_rate_override(self):
        from forge.toll.models import TollRate
        from forge.toll.rates import RateEngine
        custom = {"plan_request": TollRate(message_type="plan_request", base_rate_usd=0.1)}
        engine = RateEngine(custom_rates=custom)
        rate = engine.get_rate("plan_request")
        assert rate.base_rate_usd == 0.1

    def test_all_rates_serialization(self, rate_engine):
        all_rates = rate_engine.all_rates()
        assert isinstance(all_rates, dict)
        for k, v in all_rates.items():
            assert "base_rate_usd" in v
            assert "message_type" in v

    def test_volume_discount(self):
        from forge.toll.models import TollRate
        from forge.toll.rates import RateEngine
        custom = {
            "test": TollRate(
                message_type="test", base_rate_usd=1.0,
                volume_discount_threshold=10, volume_discount_pct=50.0,
            )
        }
        engine = RateEngine(custom_rates=custom)
        rate = engine.get_rate("test")
        # Below threshold
        assert engine.calculate(rate, session_message_count=5) == pytest.approx(1.0)
        # At/above threshold — 50% discount
        assert engine.calculate(rate, session_message_count=10) == pytest.approx(0.5)


# ── Toll Relay ────────────────────────────────────────────────────────────

class TestTollRelay:
    def _make_generator(self, messages, return_value=None):
        """Helper: create a generator that yields messages and returns a value."""
        def gen():
            for m in messages:
                yield m
            return return_value
        return gen()

    def test_meter_passthrough_when_disabled(self, ledger, rate_engine):
        from forge.toll.relay import TollRelay
        relay = TollRelay(ledger, rate_engine, enabled=False)
        msgs = [{"type": "content", "content": "hello"}]
        gen = relay.meter(self._make_generator(msgs), "a", "b")
        result = list(gen)
        assert len(result) == 1
        assert result[0]["type"] == "content"

    def test_meter_yields_original_messages(self, relay):
        msgs = [
            {"type": "content", "content": "hello world " * 20},
            {"type": "content", "content": "more content " * 20},
        ]
        gen = relay.meter(self._make_generator(msgs), "sender", "receiver", session_id="test")
        results = list(gen)
        # Should have: original msg, toll event, original msg, toll event, summary
        original_msgs = [r for r in results if r["type"] == "content"]
        assert len(original_msgs) == 2

    def test_meter_yields_toll_events(self, relay):
        msgs = [
            {"type": "content", "content": "hello world " * 20},
        ]
        gen = relay.meter(self._make_generator(msgs), "sender", "receiver", session_id="test")
        results = list(gen)
        toll_events = [r for r in results if r["type"] == "toll_deducted"]
        assert len(toll_events) == 1
        assert toll_events[0]["sender"] == "sender"
        assert toll_events[0]["receiver"] == "receiver"
        assert toll_events[0]["toll_usd"] > 0

    def test_meter_yields_summary_at_end(self, relay):
        msgs = [
            {"type": "content", "content": "hello " * 50},
        ]
        gen = relay.meter(self._make_generator(msgs), "sender", "receiver", session_id="test_sum")
        results = list(gen)
        summaries = [r for r in results if r["type"] == "toll_summary"]
        assert len(summaries) == 1
        assert summaries[0]["total_messages"] >= 1

    def test_free_messages_not_tolled(self, relay):
        msgs = [
            {"type": "status", "content": "Starting..."},
            {"type": "token_usage", "cost_usd": 0.01},
        ]
        gen = relay.meter(self._make_generator(msgs), "sender", "receiver", session_id="test_free")
        results = list(gen)
        toll_events = [r for r in results if r["type"] == "toll_deducted"]
        assert len(toll_events) == 0

    def test_meter_creates_wallets_automatically(self, relay, ledger):
        msgs = [{"type": "content", "content": "test"}]
        gen = relay.meter(self._make_generator(msgs), "new_sender", "new_receiver", session_id="auto")
        list(gen)  # consume
        assert ledger.get_wallet("new_sender") is not None
        assert ledger.get_wallet("new_receiver") is not None


# ── Settlement ────────────────────────────────────────────────────────────

class TestSettlement:
    def test_local_settlement_settle(self):
        from forge.toll.models import Transaction
        from forge.toll.settlement import LocalSettlement
        s = LocalSettlement()
        txs = [Transaction(from_wallet="a", to_wallet="b", amount_usd=0.01)]
        hashes = s.settle(txs)
        assert len(hashes) == 1

    def test_local_settlement_verify(self):
        from forge.toll.settlement import LocalSettlement
        assert LocalSettlement().verify("anything") is True


# ── Toll Endpoints ────────────────────────────────────────────────────────

class TestTollEndpoints:
    def test_balance_endpoint(self, client):
        r = client.get("/api/toll/balance")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_balance_unknown_agent(self, client):
        r = client.get("/api/toll/balance/nonexistent_agent_xyz")
        assert r.status_code == 404

    def test_deposit_endpoint(self, client):
        r = client.post("/api/toll/deposit", json={"agent_id": "test_agent", "amount_usd": 5.0})
        assert r.status_code == 200
        data = r.get_json()
        assert "transaction" in data
        assert "new_balance" in data

    def test_deposit_validation(self, client):
        r = client.post("/api/toll/deposit", json={"agent_id": "", "amount_usd": 0})
        assert r.status_code == 400

    def test_transactions_endpoint(self, client):
        r = client.get("/api/toll/transactions")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_rates_endpoint(self, client):
        r = client.get("/api/toll/rates")
        assert r.status_code == 200
        data = r.get_json()
        assert "plan_request" in data
        assert "llm_response" in data

    def test_revenue_endpoint(self, client):
        r = client.get("/api/toll/revenue")
        assert r.status_code == 200
        data = r.get_json()
        assert "total_revenue_usd" in data
        assert "revenue_by_session" in data

    def test_summary_endpoint(self, client):
        r = client.get("/api/toll/summary/nonexistent")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_messages_metered"] == 0

    def test_reset_endpoint(self, client):
        r = client.post("/api/toll/reset")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "reset"

    def test_export_endpoint(self, client):
        r = client.get("/api/toll/export")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)


# ── Toll Config ───────────────────────────────────────────────────────────

class TestTollConfig:
    def test_toll_config_exists(self):
        from forge.config import TOLL_ENABLED, TOLL_DB_PATH, TOLL_DEFAULT_BALANCE, TOLL_CREATOR_RAKE_PCT
        assert isinstance(TOLL_ENABLED, bool)
        assert TOLL_DB_PATH is not None

    def test_toll_default_balance_positive(self):
        from forge.config import TOLL_DEFAULT_BALANCE
        assert TOLL_DEFAULT_BALANCE > 0

    def test_toll_creator_rake_reasonable(self):
        from forge.config import TOLL_CREATOR_RAKE_PCT
        assert 0 <= TOLL_CREATOR_RAKE_PCT <= 100
