"""
Tests for Beat 6: Python SDK (ForgeClient).

Tests use the Flask test client via monkeypatching requests to avoid
needing a running server.
"""
import os
import sys
import uuid
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.sdk import ForgeClient, ForgeError, PaymentRequiredError


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def flask_client():
    """Flask test client."""
    from forge.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def sdk(flask_client):
    """ForgeClient that routes through the Flask test client instead of HTTP."""
    client = ForgeClient("http://testserver")

    def mock_request(method, url, **kwargs):
        """Route SDK HTTP calls through Flask test client."""
        path = url.replace("http://testserver", "")
        headers = kwargs.get("headers", {})

        flask_method = getattr(flask_client, method.lower())
        if method.upper() in ("POST", "PATCH", "PUT"):
            resp = flask_method(path, json=kwargs.get("json"), headers=headers)
        else:
            resp = flask_method(path, headers=headers)

        # Build a mock response object
        mock_resp = MagicMock()
        mock_resp.status_code = resp.status_code
        mock_resp.content = resp.data
        mock_resp.json.return_value = resp.get_json() if resp.data else {}
        return mock_resp

    with patch("forge.sdk.requests.request", side_effect=mock_request):
        yield client


# ── Registration ─────────────────────────────────────────────────────────

class TestSDKRegistration:
    def test_register(self, sdk):
        result = sdk.register(f"sdk-{uuid.uuid4().hex[:6]}", owner="test")
        assert "agent_id" in result
        assert result["api_key"].startswith("forge_")
        # Should auto-set the API key
        assert sdk.api_key == result["api_key"]

    def test_register_with_profile(self, sdk):
        result = sdk.register(
            f"sdk-prof-{uuid.uuid4().hex[:6]}",
            description="A test bot",
            capabilities=["code", "search"],
        )
        assert "agent_id" in result

    def test_register_duplicate_raises(self, sdk):
        name = f"sdk-dup-{uuid.uuid4().hex[:6]}"
        sdk.register(name)
        # Reset key so we can try again
        sdk.api_key = ""
        with pytest.raises(ForgeError) as exc_info:
            sdk.register(name)
        assert exc_info.value.status_code == 409


# ── Agent Info ───────────────────────────────────────────────────────────

class TestSDKAgentInfo:
    def test_me(self, sdk):
        sdk.register(f"sdk-me-{uuid.uuid4().hex[:6]}")
        info = sdk.me()
        assert "agent_id" in info
        assert "wallet" in info

    def test_update_profile(self, sdk):
        sdk.register(f"sdk-upd-{uuid.uuid4().hex[:6]}")
        result = sdk.update_profile(description="Updated via SDK")
        assert result["description"] == "Updated via SDK"


# ── Wallet ───────────────────────────────────────────────────────────────

class TestSDKWallet:
    def test_get_balance(self, sdk):
        sdk.register(f"sdk-bal-{uuid.uuid4().hex[:6]}")
        balance = sdk.get_balance()
        assert balance > 0

    def test_get_wallet(self, sdk):
        sdk.register(f"sdk-wal-{uuid.uuid4().hex[:6]}")
        data = sdk.get_wallet()
        assert "wallet" in data
        assert "recent_transactions" in data

    def test_deposit(self, sdk):
        sdk.register(f"sdk-dep-{uuid.uuid4().hex[:6]}")
        initial = sdk.get_balance()
        result = sdk.deposit(5.0)
        assert result["new_balance_usd"] == initial + 5.0

    def test_check_invoice(self, sdk):
        sdk.register(f"sdk-inv-{uuid.uuid4().hex[:6]}")
        # Create an invoice via ledger
        from forge.toll.public_api import _get_ledger
        ledger = _get_ledger()
        inv = ledger.create_invoice(sdk.me()["agent_id"], 1.0)
        result = sdk.check_invoice(inv.invoice_id)
        assert result["status"] == "pending"


# ── Tasks ────────────────────────────────────────────────────────────────

class TestSDKTasks:
    def test_submit_task(self, sdk):
        sdk.register(f"sdk-task-{uuid.uuid4().hex[:6]}")
        result = sdk.submit_task("echo hello")
        assert result["task_id"].startswith("ext-")
        assert "stream_url" in result

    def test_submit_broke_raises_402(self, sdk):
        sdk.register(f"sdk-broke-{uuid.uuid4().hex[:6]}")
        # Drain wallet
        from forge.toll.public_api import _get_ledger
        ledger = _get_ledger()
        agent_id = sdk.me()["agent_id"]
        with ledger._lock:
            ledger._conn.execute(
                "UPDATE wallets SET balance_usd = 0.0 WHERE agent_id = ?",
                (agent_id,),
            )
            ledger._conn.commit()

        with pytest.raises(PaymentRequiredError) as exc_info:
            sdk.submit_task("do something")
        assert exc_info.value.status_code == 402
        assert exc_info.value.invoice_id.startswith("inv_")


# ── Directory + Relay ────────────────────────────────────────────────────

class TestSDKDirectory:
    def test_list_agents(self, sdk):
        sdk.register(f"sdk-dir-{uuid.uuid4().hex[:6]}")
        agents = sdk.list_agents()
        assert isinstance(agents, list)
        assert len(agents) >= 1

    def test_invoke_agent(self, sdk, flask_client):
        # Register two agents
        sdk.register(f"sdk-inv-a-{uuid.uuid4().hex[:6]}")
        key_a = sdk.api_key

        # Register target via flask directly
        r = flask_client.post("/api/v1/agents/register", json={
            "name": f"sdk-inv-b-{uuid.uuid4().hex[:6]}",
        })
        target = r.get_json()["agent_id"]

        result = sdk.invoke_agent(target, "hello")
        assert result["task_id"].startswith("relay-")


# ── Toll Info ────────────────────────────────────────────────────────────

class TestSDKTollInfo:
    def test_get_rates(self, sdk):
        rates = sdk.get_rates()
        assert isinstance(rates, dict)
        assert len(rates) > 0

    def test_get_estimate(self, sdk):
        sdk.register(f"sdk-est-{uuid.uuid4().hex[:6]}")
        est = sdk.get_estimate("test task")
        assert "estimate_usd" in est


# ── Error Handling ───────────────────────────────────────────────────────

class TestSDKErrors:
    def test_forge_error_has_status(self):
        err = ForgeError("test", 404, {"detail": "not found"})
        assert err.status_code == 404
        assert err.data["detail"] == "not found"

    def test_payment_required_error(self):
        err = PaymentRequiredError({
            "invoice_id": "inv_test",
            "estimate_usd": 0.05,
            "shortfall_usd": 0.03,
            "payment_methods": [{"type": "api_deposit"}],
        })
        assert err.status_code == 402
        assert err.invoice_id == "inv_test"
        assert err.shortfall_usd == 0.03
