"""
Tests for the Email Agent and webhook receiver.

Tests cover:
  - Webhook HMAC-SHA256 signature validation
  - Event dispatch to EmailAgent
  - Auto-block threshold logic
  - DNS alert severity filtering
  - Email classification heuristics
  - Agent start/stop lifecycle
"""
import hashlib
import hmac
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ────────────────────────────────────────────────────────────────

def _sign(payload: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature like ARC-Relay."""
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


# ── Webhook Signature Tests ──────────────────────────────────────────────

class TestWebhookSignature:
    def test_valid_signature_accepted(self):
        from forge.agents.email_webhook import _verify_signature, configure
        from forge.agents.email_agent import EmailAgent

        agent = EmailAgent()
        configure("test-secret-123", agent)

        payload = b'{"type":"forward.success","data":{}}'
        sig = _sign(payload, "test-secret-123")
        assert _verify_signature(payload, sig) is True

    def test_invalid_signature_rejected(self):
        from forge.agents.email_webhook import _verify_signature, configure
        configure("test-secret-123", None)

        payload = b'{"type":"forward.success"}'
        assert _verify_signature(payload, "sha256=badhex") is False

    def test_empty_secret_rejected(self):
        from forge.agents.email_webhook import _verify_signature, configure
        configure("", None)

        payload = b'{"type":"test"}'
        sig = _sign(payload, "")
        assert _verify_signature(payload, sig) is False

    def test_missing_signature_rejected(self):
        from forge.agents.email_webhook import _verify_signature, configure
        configure("secret", None)

        assert _verify_signature(b"data", "") is False


class TestWebhookEndpoint:
    @pytest.fixture
    def client(self):
        # Import fresh to avoid state leakage
        from forge.agents.email_webhook import email_webhook_bp, configure
        from forge.agents.email_agent import EmailAgent
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True
        agent = EmailAgent()
        configure("webhook-test-secret", agent)
        app.register_blueprint(email_webhook_bp)

        with app.test_client() as c:
            yield c, agent

    def test_valid_webhook_returns_200(self, client):
        c, agent = client
        payload = json.dumps({"type": "forward.success", "data": {"sender": "a@b.com"}}).encode()
        sig = _sign(payload, "webhook-test-secret")
        r = c.post("/webhooks/arcrelay", data=payload,
                    content_type="application/json",
                    headers={"X-ArcRelay-Signature": sig})
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_invalid_signature_returns_401(self, client):
        c, agent = client
        payload = json.dumps({"type": "test"}).encode()
        r = c.post("/webhooks/arcrelay", data=payload,
                    content_type="application/json",
                    headers={"X-ArcRelay-Signature": "sha256=bad"})
        assert r.status_code == 401

    def test_missing_type_returns_400(self, client):
        c, agent = client
        payload = json.dumps({"data": {}}).encode()
        sig = _sign(payload, "webhook-test-secret")
        r = c.post("/webhooks/arcrelay", data=payload,
                    content_type="application/json",
                    headers={"X-ArcRelay-Signature": sig})
        assert r.status_code == 400

    def test_event_queued_to_agent(self, client):
        c, agent = client
        event = {"type": "forward.success", "data": {"sender": "x@y.com"}}
        payload = json.dumps(event).encode()
        sig = _sign(payload, "webhook-test-secret")
        c.post("/webhooks/arcrelay", data=payload,
               content_type="application/json",
               headers={"X-ArcRelay-Signature": sig})
        # Event should be in the queue (agent not started, so not consumed)
        assert agent._event_queue.qsize() == 1


# ── EmailAgent Tests ─────────────────────────────────────────────────────

class TestEmailAgent:
    def test_start_stop(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        agent.start()
        assert agent._running is True
        agent.stop()
        assert agent._running is False

    def test_handle_event_queues(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        agent.handle_event({"type": "test", "data": {}})
        assert agent._event_queue.qsize() == 1

    def test_dispatch_forward_success(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        event = {"type": "forward.success", "data": {"sender": "a@b.com", "subject": "Hello", "domain": "test.com"}}
        agent._dispatch(event)
        assert len(agent._processed_events) == 1

    def test_dispatch_forward_rejected_tracks_count(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        event = {"type": "forward.rejected", "data": {"sender": "spam@bad.com", "reason": "blocked"}}
        agent._dispatch(event)
        assert agent._rejection_counts["spam@bad.com"] == 1

    def test_auto_block_after_threshold(self):
        from forge.agents.email_agent import EmailAgent, AUTO_BLOCK_THRESHOLD
        agent = EmailAgent()
        for i in range(AUTO_BLOCK_THRESHOLD):
            agent._dispatch({"type": "forward.rejected", "data": {"sender": "repeat@offender.com", "reason": "spam"}})
        assert "repeat@offender.com" in agent._blocked_senders
        assert agent._rejection_counts["repeat@offender.com"] == AUTO_BLOCK_THRESHOLD

    def test_no_auto_block_below_threshold(self):
        from forge.agents.email_agent import EmailAgent, AUTO_BLOCK_THRESHOLD
        agent = EmailAgent()
        for i in range(AUTO_BLOCK_THRESHOLD - 1):
            agent._dispatch({"type": "forward.rejected", "data": {"sender": "almost@there.com", "reason": "x"}})
        assert "almost@there.com" not in agent._blocked_senders

    def test_dns_event_processed(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        event = {"type": "dns.dmarc_changed", "data": {"severity": "warning", "domain": "test.com", "message": "policy changed"}}
        agent._dispatch(event)
        assert len(agent._processed_events) == 1

    def test_unknown_event_type(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        agent._dispatch({"type": "unknown.event", "data": {}})
        assert len(agent._processed_events) == 1  # still tracked

    def test_stats(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        agent._dispatch({"type": "forward.success", "data": {}})
        stats = agent.stats
        assert stats["events_processed"] == 1
        assert stats["running"] is False


# ── Classification Tests ─────────────────────────────────────────────────

class TestEmailClassification:
    def test_financial(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        assert agent._classify_email("billing@co.com", "Your Invoice #123") == "financial"

    def test_urgent(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        assert agent._classify_email("alert@sys.com", "URGENT: Action Required") == "urgent"

    def test_newsletter(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        assert agent._classify_email("news@co.com", "Weekly Newsletter - Issue 42") == "newsletter"

    def test_automated(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        assert agent._classify_email("noreply@co.com", "Your order confirmation") == "automated"

    def test_general(self):
        from forge.agents.email_agent import EmailAgent
        agent = EmailAgent()
        assert agent._classify_email("john@co.com", "Hey, quick question") == "general"


# ── Config Tests ──────────────────────────────────────────────────────────

class TestEmailAgentConfig:
    def test_config_vars_exist(self):
        from forge.config import ARCRELAY_WEBHOOK_SECRET, ARCRELAY_API_KEY, EMAIL_AGENT_ENABLED, EMAIL_AGENT_MODEL
        assert isinstance(ARCRELAY_WEBHOOK_SECRET, str)
        assert isinstance(ARCRELAY_API_KEY, str)
        assert isinstance(EMAIL_AGENT_ENABLED, bool)
        assert isinstance(EMAIL_AGENT_MODEL, str)

    def test_email_agent_disabled_by_default(self):
        from forge.config import EMAIL_AGENT_ENABLED
        assert EMAIL_AGENT_ENABLED is False
