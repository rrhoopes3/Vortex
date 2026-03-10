"""
Tests for Beat 3: Agent Marketplace + x402 Toll Gate.

Covers:
  - API key CRUD (ledger integration)
  - @require_api_key decorator
  - @toll_gate decorator + HTTP 402 flow
  - Agent registration
  - Wallet operations
  - Task submission + ownership
  - Public rate endpoint
  - Config validation
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path):
    """Isolated ledger with api_keys table."""
    from forge.toll.ledger import Ledger
    return Ledger(tmp_path / "test_marketplace.db")


@pytest.fixture
def client():
    """Flask test client with marketplace enabled."""
    from forge.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def registered_agent(client):
    """Register a test agent with unique name and return (agent_id, api_key, wallet)."""
    import uuid
    unique_name = f"test-bot-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/agents/register", json={
        "name": unique_name,
        "owner": "test-owner",
    })
    data = r.get_json()
    return data["agent_id"], data["api_key"], data["wallet"]


# ── API Key CRUD (Ledger) ────────────────────────────────────────────────

class TestAPIKeyCRUD:
    def test_create_api_key(self, ledger):
        key = ledger.create_api_key("agent_1", "alice")
        assert key.api_key.startswith("forge_")
        assert key.agent_id == "agent_1"
        assert key.owner_id == "alice"
        assert not key.is_revoked

    def test_validate_api_key(self, ledger):
        key = ledger.create_api_key("agent_2", "bob")
        result = ledger.validate_api_key(key.api_key)
        assert result is not None
        assert result.agent_id == "agent_2"
        assert result.last_used_at is not None

    def test_validate_nonexistent_key(self, ledger):
        result = ledger.validate_api_key("forge_doesnotexist")
        assert result is None

    def test_validate_revoked_key(self, ledger):
        key = ledger.create_api_key("agent_3")
        ledger.revoke_api_key(key.api_key)
        result = ledger.validate_api_key(key.api_key)
        assert result is None

    def test_revoke_api_key(self, ledger):
        key = ledger.create_api_key("agent_4")
        assert ledger.revoke_api_key(key.api_key) is True
        # Double revoke returns False
        assert ledger.revoke_api_key(key.api_key) is False

    def test_get_api_keys(self, ledger):
        ledger.create_api_key("agent_5", "carol")
        ledger.create_api_key("agent_5", "carol")
        keys = ledger.get_api_keys("agent_5")
        assert len(keys) == 2
        assert all(k.agent_id == "agent_5" for k in keys)

    def test_api_key_format(self, ledger):
        key = ledger.create_api_key("agent_6")
        assert key.api_key.startswith("forge_")
        # 32-char hex after prefix
        hex_part = key.api_key[6:]
        assert len(hex_part) == 32
        int(hex_part, 16)  # should not raise

    def test_reset_clears_api_keys(self, ledger):
        ledger.create_api_key("agent_7")
        ledger.reset()
        keys = ledger.get_api_keys("agent_7")
        assert len(keys) == 0


# ── @require_api_key Decorator ───────────────────────────────────────────

class TestRequireAPIKey:
    def test_missing_key_returns_401(self, client):
        r = client.get("/api/v1/agents/me")
        assert r.status_code == 401
        data = r.get_json()
        assert data["error"] == "authentication_required"

    def test_invalid_key_returns_401(self, client):
        r = client.get("/api/v1/agents/me",
                        headers={"X-API-Key": "forge_invalid"})
        assert r.status_code == 401
        data = r.get_json()
        assert data["error"] == "invalid_api_key"

    def test_valid_key_succeeds(self, client, registered_agent):
        agent_id, api_key, _ = registered_agent
        r = client.get("/api/v1/agents/me",
                        headers={"X-API-Key": api_key})
        assert r.status_code == 200
        data = r.get_json()
        assert data["agent_id"] == agent_id

    def test_bearer_auth_works(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.get("/api/v1/agents/me",
                        headers={"Authorization": f"Bearer {api_key}"})
        assert r.status_code == 200

    def test_non_forge_bearer_rejected(self, client):
        r = client.get("/api/v1/agents/me",
                        headers={"Authorization": "Bearer sk_notforge"})
        assert r.status_code == 401


# ── Agent Registration ───────────────────────────────────────────────────

class TestRegistration:
    def test_register_agent(self, client):
        r = client.post("/api/v1/agents/register", json={
            "name": "my-cool-bot",
            "owner": "test",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["agent_id"] == "ext_my-cool-bot"
        assert data["api_key"].startswith("forge_")
        assert "wallet" in data

    def test_register_no_name(self, client):
        r = client.post("/api/v1/agents/register", json={"owner": "test"})
        assert r.status_code == 400

    def test_register_duplicate_rejected(self, client):
        client.post("/api/v1/agents/register", json={"name": "dup-bot"})
        r = client.post("/api/v1/agents/register", json={"name": "dup-bot"})
        assert r.status_code == 409
        assert "already_registered" in r.get_json()["error"]

    def test_register_sanitizes_name(self, client):
        r = client.post("/api/v1/agents/register", json={
            "name": "My Bot!@#$%",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["agent_id"].startswith("ext_my-bot")

    def test_register_default_balance(self, client):
        r = client.post("/api/v1/agents/register", json={"name": "balance-bot"})
        data = r.get_json()
        assert data["wallet"]["balance_usd"] > 0


# ── Wallet Operations ───────────────────────────────────────────────────

class TestWalletOps:
    def test_get_wallet(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.get("/api/v1/wallet",
                        headers={"X-API-Key": api_key})
        assert r.status_code == 200
        data = r.get_json()
        assert "wallet" in data
        assert "recent_transactions" in data

    def test_deposit(self, client, registered_agent):
        _, api_key, wallet = registered_agent
        initial = wallet["balance_usd"]
        r = client.post("/api/v1/wallet/deposit",
                         json={"amount_usd": 5.0},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 200
        data = r.get_json()
        assert data["new_balance_usd"] == initial + 5.0
        assert data["transaction"]["tx_type"] == "deposit"

    def test_deposit_zero_rejected(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.post("/api/v1/wallet/deposit",
                         json={"amount_usd": 0},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 400

    def test_deposit_negative_rejected(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.post("/api/v1/wallet/deposit",
                         json={"amount_usd": -10},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 400


# ── HTTP 402 Toll Gate ───────────────────────────────────────────────────

class TestTollGate:
    def test_402_when_broke(self, client):
        """Agent with zero balance gets 402."""
        # Register an agent
        r = client.post("/api/v1/agents/register", json={"name": "broke-bot"})
        data = r.get_json()
        api_key = data["api_key"]
        agent_id = data["agent_id"]

        # Drain the wallet by submitting enough info to get past auth
        # but the gate should reject based on configured estimate
        # First, let's just set balance to 0 by using the internal ledger
        from forge.toll.public_api import _get_ledger
        ledger = _get_ledger()
        # Set balance to 0
        with ledger._lock:
            ledger._conn.execute(
                "UPDATE wallets SET balance_usd = 0.0 WHERE agent_id = ?",
                (agent_id,),
            )
            ledger._conn.commit()

        r = client.post("/api/v1/tasks",
                         json={"task": "do something"},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 402
        data = r.get_json()
        assert data["error"] == "payment_required"
        assert "estimate_usd" in data
        assert "shortfall_usd" in data
        assert "payment_methods" in data
        assert any(m["type"] == "api_deposit" for m in data["payment_methods"])

    def test_402_includes_invoice_id(self, client):
        """402 response includes a unique invoice ID."""
        r = client.post("/api/v1/agents/register", json={"name": "invoice-bot"})
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
        assert data["invoice_id"].startswith("inv_")


# ── Task Submission ──────────────────────────────────────────────────────

class TestTaskSubmission:
    def test_submit_no_task(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.post("/api/v1/tasks",
                         json={"task": ""},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 400

    def test_submit_no_auth(self, client):
        r = client.post("/api/v1/tasks",
                         json={"task": "do something"})
        assert r.status_code == 401

    def test_submit_returns_task_id(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.post("/api/v1/tasks",
                         json={"task": "list files in current directory"},
                         headers={"X-API-Key": api_key})
        # Should be 202 (accepted) if balance OK
        assert r.status_code == 202
        data = r.get_json()
        assert data["task_id"].startswith("ext-")
        assert "stream_url" in data
        assert "result_url" in data

    def test_result_not_owned(self, client, registered_agent):
        """Can't access another agent's task result."""
        # Register a second agent
        r2 = client.post("/api/v1/agents/register", json={"name": "other-bot"})
        other_key = r2.get_json()["api_key"]

        r = client.get("/api/v1/tasks/ext-fake123/result",
                        headers={"X-API-Key": other_key})
        assert r.status_code == 404


# ── Public Info Endpoints ────────────────────────────────────────────────

class TestPublicInfo:
    def test_toll_rates_public(self, client):
        """Rates endpoint is accessible without auth."""
        r = client.get("/api/v1/toll/rates")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_toll_estimate_requires_auth(self, client):
        r = client.get("/api/v1/toll/estimate")
        assert r.status_code == 401

    def test_toll_estimate_with_auth(self, client, registered_agent):
        _, api_key, _ = registered_agent
        r = client.get("/api/v1/toll/estimate?task=hello",
                        headers={"X-API-Key": api_key})
        assert r.status_code == 200
        data = r.get_json()
        assert "estimate_usd" in data


# ── Marketplace Config ───────────────────────────────────────────────────

class TestMarketplaceConfig:
    def test_marketplace_enabled(self):
        from forge.config import MARKETPLACE_ENABLED
        assert isinstance(MARKETPLACE_ENABLED, bool)

    def test_default_balance_positive(self):
        from forge.config import MARKETPLACE_DEFAULT_BALANCE
        assert MARKETPLACE_DEFAULT_BALANCE > 0

    def test_task_estimate_positive(self):
        from forge.config import MARKETPLACE_TASK_ESTIMATE
        assert MARKETPLACE_TASK_ESTIMATE > 0

    def test_payment_addresses_are_strings(self):
        from forge.config import MARKETPLACE_BASE_USDC_ADDRESS, MARKETPLACE_SOLANA_USDC_ADDRESS
        assert isinstance(MARKETPLACE_BASE_USDC_ADDRESS, str)
        assert isinstance(MARKETPLACE_SOLANA_USDC_ADDRESS, str)


# ── Orchestrator toll_sender ─────────────────────────────────────────────

class TestOrchestratorTollSender:
    def test_toll_sender_param_accepted(self):
        """Orchestrator accepts toll_sender without crashing."""
        from forge.orchestrator import Orchestrator
        # Just verify it initializes — don't run tasks
        orch = Orchestrator(toll_sender="ext_test-bot", task_id="test123")
        assert orch._toll_sender == "ext_test-bot"

    def test_toll_sender_default_empty(self):
        from forge.orchestrator import Orchestrator
        orch = Orchestrator(task_id="test456")
        assert orch._toll_sender == ""
