"""
Tests for Beat 5: Agent-to-Agent Relay.

Covers:
  - Agent profile CRUD (ledger)
  - Agent directory endpoint
  - Profile update endpoint
  - Agent invocation (relay) endpoint
  - Registration creates profile
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path):
    from forge.toll.ledger import Ledger
    return Ledger(tmp_path / "test_relay.db")


@pytest.fixture
def client():
    from forge.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, name=None):
    """Register a unique agent, return (agent_id, api_key)."""
    name = name or f"bot-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/agents/register", json={
        "name": name,
        "owner": "test",
        "description": "A test bot",
        "capabilities": ["code", "search"],
    })
    data = r.get_json()
    return data["agent_id"], data["api_key"]


# ── Profile CRUD (Ledger) ────────────────────────────────────────────────

class TestProfileCRUD:
    def test_create_profile(self, ledger):
        p = ledger.create_agent_profile("ext_bot", "bot", "Does stuff", ["code"])
        assert p.agent_id == "ext_bot"
        assert p.name == "bot"
        assert p.description == "Does stuff"
        assert p.capabilities == ["code"]
        assert p.is_public is True

    def test_get_profile(self, ledger):
        ledger.create_agent_profile("ext_get", "get-bot")
        p = ledger.get_agent_profile("ext_get")
        assert p is not None
        assert p.name == "get-bot"

    def test_get_nonexistent(self, ledger):
        assert ledger.get_agent_profile("ext_nope") is None

    def test_list_profiles(self, ledger):
        ledger.create_agent_profile("ext_a", "alpha")
        ledger.create_agent_profile("ext_b", "beta")
        profiles = ledger.list_agent_profiles()
        assert len(profiles) == 2
        names = [p.name for p in profiles]
        assert "alpha" in names
        assert "beta" in names

    def test_list_public_only(self, ledger):
        ledger.create_agent_profile("ext_pub", "public-bot")
        p = ledger.create_agent_profile("ext_priv", "private-bot")
        ledger.update_agent_profile("ext_priv", is_public=False)
        public = ledger.list_agent_profiles(public_only=True)
        assert len(public) == 1
        assert public[0].agent_id == "ext_pub"

    def test_update_profile(self, ledger):
        ledger.create_agent_profile("ext_upd", "upd-bot")
        updated = ledger.update_agent_profile(
            "ext_upd", description="New desc", capabilities=["math"]
        )
        assert updated.description == "New desc"
        assert updated.capabilities == ["math"]

    def test_update_nonexistent(self, ledger):
        assert ledger.update_agent_profile("ext_nope", description="x") is None

    def test_upsert_profile(self, ledger):
        ledger.create_agent_profile("ext_up", "first")
        ledger.create_agent_profile("ext_up", "second")
        p = ledger.get_agent_profile("ext_up")
        assert p.name == "second"

    def test_reset_clears_profiles(self, ledger):
        ledger.create_agent_profile("ext_r", "reset-bot")
        ledger.reset()
        assert ledger.get_agent_profile("ext_r") is None


# ── Directory Endpoint ───────────────────────────────────────────────────

class TestDirectory:
    def test_empty_directory(self, client):
        r = client.get("/api/v1/agents")
        assert r.status_code == 200
        # May have agents from other tests, just check it's a list
        assert isinstance(r.get_json(), list)

    def test_directory_includes_registered(self, client):
        agent_id, _ = _register(client, f"dir-{uuid.uuid4().hex[:6]}")
        r = client.get("/api/v1/agents")
        assert r.status_code == 200
        agents = r.get_json()
        ids = [a["agent_id"] for a in agents]
        assert agent_id in ids

    def test_directory_no_auth_required(self, client):
        """Directory is public — no API key needed."""
        r = client.get("/api/v1/agents")
        assert r.status_code == 200

    def test_registration_creates_profile(self, client):
        r = client.post("/api/v1/agents/register", json={
            "name": f"prof-{uuid.uuid4().hex[:6]}",
            "description": "I do things",
            "capabilities": ["code", "search"],
        })
        assert r.status_code == 201
        agent_id = r.get_json()["agent_id"]

        # Check profile is in directory
        r2 = client.get("/api/v1/agents")
        agents = r2.get_json()
        profile = next((a for a in agents if a["agent_id"] == agent_id), None)
        assert profile is not None
        assert profile["description"] == "I do things"
        assert "code" in profile["capabilities"]


# ── Profile Update Endpoint ─────────────────────────────────────────────

class TestProfileUpdate:
    def test_update_description(self, client):
        _, api_key = _register(client)
        r = client.patch("/api/v1/agents/me/profile",
                         json={"description": "Updated description"},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 200
        assert r.get_json()["description"] == "Updated description"

    def test_update_capabilities(self, client):
        _, api_key = _register(client)
        r = client.patch("/api/v1/agents/me/profile",
                         json={"capabilities": ["math", "writing"]},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 200
        assert r.get_json()["capabilities"] == ["math", "writing"]

    def test_update_visibility(self, client):
        agent_id, api_key = _register(client)
        r = client.patch("/api/v1/agents/me/profile",
                         json={"is_public": False},
                         headers={"X-API-Key": api_key})
        assert r.status_code == 200
        assert r.get_json()["is_public"] is False

    def test_update_requires_auth(self, client):
        r = client.patch("/api/v1/agents/me/profile",
                         json={"description": "x"})
        assert r.status_code == 401


# ── Invoke (Relay) Endpoint ──────────────────────────────────────────────

class TestInvoke:
    def test_invoke_returns_task(self, client):
        """Agent A invokes Agent B — should get a relay task ID."""
        agent_a, key_a = _register(client)
        agent_b, _ = _register(client)

        r = client.post(f"/api/v1/agents/{agent_b}/invoke",
                        json={"task": "say hello"},
                        headers={"X-API-Key": key_a})
        assert r.status_code == 202
        data = r.get_json()
        assert data["task_id"].startswith("relay-")
        assert data["relay"]["caller"] == agent_a
        assert data["relay"]["target"] == agent_b

    def test_invoke_unknown_agent(self, client):
        _, key_a = _register(client)
        r = client.post("/api/v1/agents/ext_nonexistent/invoke",
                        json={"task": "hello"},
                        headers={"X-API-Key": key_a})
        assert r.status_code == 404

    def test_invoke_self_rejected(self, client):
        agent_id, api_key = _register(client)
        r = client.post(f"/api/v1/agents/{agent_id}/invoke",
                        json={"task": "hello"},
                        headers={"X-API-Key": api_key})
        assert r.status_code == 400

    def test_invoke_no_task(self, client):
        _, key_a = _register(client)
        agent_b, _ = _register(client)
        r = client.post(f"/api/v1/agents/{agent_b}/invoke",
                        json={"task": ""},
                        headers={"X-API-Key": key_a})
        assert r.status_code == 400

    def test_invoke_requires_auth(self, client):
        agent_b, _ = _register(client)
        r = client.post(f"/api/v1/agents/{agent_b}/invoke",
                        json={"task": "hello"})
        assert r.status_code == 401

    def test_invoke_broke_agent_gets_402(self, client):
        agent_a, key_a = _register(client)
        agent_b, _ = _register(client)

        # Drain caller's wallet
        from forge.toll.public_api import _get_ledger
        ledger = _get_ledger()
        with ledger._lock:
            ledger._conn.execute(
                "UPDATE wallets SET balance_usd = 0.0 WHERE agent_id = ?",
                (agent_a,),
            )
            ledger._conn.commit()

        r = client.post(f"/api/v1/agents/{agent_b}/invoke",
                        json={"task": "hello"},
                        headers={"X-API-Key": key_a})
        assert r.status_code == 402
