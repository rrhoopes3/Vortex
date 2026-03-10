"""
Tests for email tools — wrapping ARC-Relay REST API.

Tests cover:
  - All 10 tool handlers with mocked HTTP responses
  - URL construction & header passing
  - Error handling (HTTP errors, network errors)
  - Registry integration (category resolution, tool listing)
"""
import json
import os
import sys
import urllib.error
from unittest.mock import patch, MagicMock
from io import BytesIO

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ────────────────────────────────────────────────────────────────

def _mock_response(body: dict, status: int = 200):
    """Create a mock urllib response."""
    data = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = data
    resp.status = status
    resp.url = "https://arc-relay.com/api/test"
    resp.headers = {"Content-Type": "application/json"}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_http_error(code: int, reason: str, body: str = ""):
    """Create a mock HTTPError."""
    err = urllib.error.HTTPError(
        url="https://arc-relay.com/api/test",
        code=code,
        msg=reason,
        hdrs={},
        fp=BytesIO(body.encode("utf-8")),
    )
    return err


# ── Fix config for tests ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_email_api_url():
    """Ensure email module uses test URL."""
    import forge.tools.email as em
    em._api_url = "https://arc-relay.com"
    yield
    em._api_url = None


# ── Public Tools ──────────────────────────────────────────────────────────

class TestEmailCheckDmarc:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_check_dmarc
        body = {"domain": "example.com", "dmarc": {"status": "found"}, "spf": {"status": "found"}, "mx": {"status": "found"}}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_check_dmarc("example.com"))
        assert result["domain"] == "example.com"
        assert result["dmarc"]["status"] == "found"

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_url_construction(self, mock_urlopen):
        from forge.tools.email import email_check_dmarc
        mock_urlopen.return_value = _mock_response({"domain": "test.io"})
        email_check_dmarc("test.io")
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "/api/tools/dmarc/test.io" in req.full_url


class TestEmailCheckHealth:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_check_health
        body = {"score": 85, "checks": {}, "recommendations": []}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_check_health("example.com"))
        assert result["score"] == 85

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_no_auth_header(self, mock_urlopen):
        from forge.tools.email import email_check_health
        mock_urlopen.return_value = _mock_response({"score": 50})
        email_check_health("test.com")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None


# ── Authenticated Tools ───────────────────────────────────────────────────

class TestEmailListDomains:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_list_domains
        body = {"domains": [{"id": "d1", "domain": "test.com", "status": "verified"}]}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_list_domains("ar_live_xxx"))
        assert len(result["domains"]) == 1

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_auth_header(self, mock_urlopen):
        from forge.tools.email import email_list_domains
        mock_urlopen.return_value = _mock_response({"domains": []})
        email_list_domains("ar_live_testkey")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer ar_live_testkey"


class TestEmailAddDomain:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_add_domain
        body = {"domain": {"id": "d2", "domain": "new.com", "status": "pending"}}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_add_domain("ar_live_xxx", "new.com"))
        assert result["domain"]["status"] == "pending"

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_sends_post_body(self, mock_urlopen):
        from forge.tools.email import email_add_domain
        mock_urlopen.return_value = _mock_response({"domain": {}})
        email_add_domain("ar_live_xxx", "newdomain.org")
        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        sent_body = json.loads(req.data.decode("utf-8"))
        assert sent_body["domain"] == "newdomain.org"


class TestEmailVerifyDomain:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_verify_domain
        body = {"verified": True, "mx_pointed": True, "status": "verified"}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_verify_domain("ar_live_xxx", "domain-uuid-1"))
        assert result["verified"] is True

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_url_includes_domain_id(self, mock_urlopen):
        from forge.tools.email import email_verify_domain
        mock_urlopen.return_value = _mock_response({"verified": False})
        email_verify_domain("ar_live_xxx", "abc-123")
        req = mock_urlopen.call_args[0][0]
        assert "/api/domains/abc-123/verify" in req.full_url


class TestEmailListAliases:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_list_aliases
        body = {"aliases": [{"id": "a1", "alias": "info", "forward_to": "me@test.com"}]}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_list_aliases("ar_live_xxx", "d1"))
        assert result["aliases"][0]["alias"] == "info"


class TestEmailCreateAlias:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_create_alias
        body = {"alias": {"id": "a2", "alias": "support", "forward_to": "help@me.com"}}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_create_alias("ar_live_xxx", "d1", "support", "help@me.com"))
        assert result["alias"]["alias"] == "support"

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_post_body(self, mock_urlopen):
        from forge.tools.email import email_create_alias
        mock_urlopen.return_value = _mock_response({"alias": {}})
        email_create_alias("ar_live_xxx", "d1", "sales", "sales@corp.com")
        req = mock_urlopen.call_args[0][0]
        sent = json.loads(req.data.decode("utf-8"))
        assert sent["alias"] == "sales"
        assert sent["forward_to"] == "sales@corp.com"


class TestEmailGetLogs:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_get_logs
        body = {"logs": [{"id": "l1", "status": "delivered"}], "total": 1, "page": 1}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_get_logs("ar_live_xxx"))
        assert result["total"] == 1

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_query_params(self, mock_urlopen):
        from forge.tools.email import email_get_logs
        mock_urlopen.return_value = _mock_response({"logs": [], "total": 0})
        email_get_logs("ar_live_xxx", page=2, limit=25, domain="test.com", status="rejected")
        req = mock_urlopen.call_args[0][0]
        assert "page=2" in req.full_url
        assert "limit=25" in req.full_url
        assert "domain=test.com" in req.full_url
        assert "status=rejected" in req.full_url

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_limit_capped_at_100(self, mock_urlopen):
        from forge.tools.email import email_get_logs
        mock_urlopen.return_value = _mock_response({"logs": []})
        email_get_logs("ar_live_xxx", limit=500)
        req = mock_urlopen.call_args[0][0]
        assert "limit=100" in req.full_url


class TestEmailBlockSender:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_block_email(self, mock_urlopen):
        from forge.tools.email import email_block_sender
        body = {"rule": {"id": "r1", "sender_pattern": "spam@bad.com", "action": "block"}}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_block_sender("ar_live_xxx", "spam@bad.com"))
        assert result["rule"]["action"] == "block"

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_block_domain_pattern(self, mock_urlopen):
        from forge.tools.email import email_block_sender
        mock_urlopen.return_value = _mock_response({"rule": {}})
        email_block_sender("ar_live_xxx", "@bad.com", domain_id="d1")
        req = mock_urlopen.call_args[0][0]
        sent = json.loads(req.data.decode("utf-8"))
        assert sent["sender_pattern"] == "@bad.com"
        assert sent["domain_id"] == "d1"
        assert sent["action"] == "block"


class TestEmailGetAnalytics:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from forge.tools.email import email_get_analytics
        body = {"forwards7d": 42, "forwards30d": 180, "rejectionRate": 0.05}
        mock_urlopen.return_value = _mock_response(body)
        result = json.loads(email_get_analytics("ar_live_xxx"))
        assert result["forwards7d"] == 42


# ── Error Handling ────────────────────────────────────────────────────────

class TestErrorHandling:
    @patch("forge.tools.email.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        from forge.tools.email import email_check_dmarc
        mock_urlopen.side_effect = _mock_http_error(404, "Not Found")
        result = json.loads(email_check_dmarc("nonexistent.xyz"))
        assert "error" in result
        assert "404" in result["error"]

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_url_error(self, mock_urlopen):
        from forge.tools.email import email_check_dmarc
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        result = json.loads(email_check_dmarc("offline.com"))
        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_http_402_payment_required(self, mock_urlopen):
        from forge.tools.email import email_list_domains
        err_body = json.dumps({"error": "payment_required", "shortfall_usd": 0.03})
        mock_urlopen.side_effect = _mock_http_error(402, "Payment Required", err_body)
        result = json.loads(email_list_domains("ar_live_xxx"))
        assert "402" in result["error"]
        body = json.loads(result["body"])
        assert body["error"] == "payment_required"


# ── Registry Integration ─────────────────────────────────────────────────

class TestEmailRegistry:
    def test_email_tools_registered(self):
        from forge.tools import create_registry
        registry = create_registry()
        tools = registry.list_tools()
        expected = [
            "email_check_dmarc", "email_check_health",
            "email_list_domains", "email_add_domain", "email_verify_domain",
            "email_list_aliases", "email_create_alias",
            "email_get_logs", "email_block_sender", "email_get_analytics",
        ]
        for t in expected:
            assert t in tools, f"Missing tool: {t}"

    def test_email_category_in_registry(self):
        from forge.tools.registry import TOOL_CATEGORIES
        assert "email" in TOOL_CATEGORIES
        assert len(TOOL_CATEGORIES["email"]) == 10

    def test_resolve_email_category(self):
        from forge.tools.registry import resolve_tools_for_step, CORE_TOOLS
        resolved = resolve_tools_for_step(["email"])
        assert CORE_TOOLS.issubset(resolved)
        assert "email_check_dmarc" in resolved
        assert "email_block_sender" in resolved
        assert "email_get_analytics" in resolved

    def test_resolve_single_email_tool(self):
        from forge.tools.registry import resolve_tools_for_step
        resolved = resolve_tools_for_step(["email_check_dmarc"])
        assert "email_check_dmarc" in resolved

    @patch("forge.tools.email.urllib.request.urlopen")
    def test_execute_via_registry(self, mock_urlopen):
        from forge.tools import create_registry
        registry = create_registry()
        mock_urlopen.return_value = _mock_response({"score": 90})
        result = registry.execute("email_check_health", {"domain": "test.com"})
        parsed = json.loads(result)
        assert parsed["score"] == 90


# ── Config ────────────────────────────────────────────────────────────────

class TestEmailConfig:
    def test_arcrelay_url_in_config(self):
        from forge.config import ARCRELAY_API_URL
        assert ARCRELAY_API_URL
        assert "arc-relay" in ARCRELAY_API_URL.lower() or ARCRELAY_API_URL.startswith("http")
