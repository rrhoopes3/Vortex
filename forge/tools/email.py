"""
Email tools — wraps ARC-Relay REST API endpoints.

10 tools for domain management, alias creation, DMARC/health checks,
log retrieval, sender blocking, and analytics.

Public tools (no auth): email_check_dmarc, email_check_health
Authenticated tools: everything else (requires api_key param)
"""
from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
import urllib.parse

from .registry import ToolRegistry

log = logging.getLogger("forge.tools.email")

# Loaded lazily to avoid circular imports
_api_url: str | None = None


def _get_api_url() -> str:
    global _api_url
    if _api_url is None:
        from forge.config import ARCRELAY_API_URL
        _api_url = ARCRELAY_API_URL.rstrip("/")
    return _api_url


def _arcrelay_request(
    method: str,
    path: str,
    api_key: str = "",
    body: dict | None = None,
    query: dict | None = None,
) -> str:
    """Make an HTTP request to ARC-Relay and return JSON string result."""
    base = _get_api_url()
    url = f"{base}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v})

    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "TheForge/1.0")
        req.add_header("Content-Type", "application/json")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            return resp_body[:6_000] if resp_body else "{}"

    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:2_000]
        except Exception:
            pass
        return json.dumps({"error": f"HTTP {e.code}: {e.reason}", "body": err_body})
    except urllib.error.URLError as e:
        return json.dumps({"error": f"URL error: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ── Public Tools (no auth) ─────────────────────────────────────────────────


def email_check_dmarc(domain: str) -> str:
    """Check DMARC, SPF, and MX records for a domain."""
    return _arcrelay_request("GET", f"/api/tools/dmarc/{urllib.parse.quote(domain)}")


def email_check_health(domain: str) -> str:
    """Get email health score and recommendations for a domain."""
    return _arcrelay_request("GET", f"/api/tools/health/{urllib.parse.quote(domain)}")


# ── Authenticated Tools ────────────────────────────────────────────────────


def email_list_domains(api_key: str) -> str:
    """List all domains for the authenticated user."""
    return _arcrelay_request("GET", "/api/domains", api_key=api_key)


def email_add_domain(api_key: str, domain: str) -> str:
    """Add a domain to the user's account."""
    return _arcrelay_request("POST", "/api/domains", api_key=api_key,
                             body={"domain": domain})


def email_verify_domain(api_key: str, domain_id: str) -> str:
    """Verify DNS records for a domain (checks TXT and MX)."""
    return _arcrelay_request("POST", f"/api/domains/{urllib.parse.quote(domain_id)}/verify",
                             api_key=api_key)


def email_list_aliases(api_key: str, domain_id: str) -> str:
    """List all email aliases for a domain."""
    return _arcrelay_request("GET", f"/api/domains/{urllib.parse.quote(domain_id)}/aliases",
                             api_key=api_key)


def email_create_alias(api_key: str, domain_id: str, alias: str, forward_to: str) -> str:
    """Create a new email alias that forwards to the given address."""
    return _arcrelay_request("POST", f"/api/domains/{urllib.parse.quote(domain_id)}/aliases",
                             api_key=api_key,
                             body={"alias": alias, "forward_to": forward_to})


def email_get_logs(api_key: str, page: int = 1, limit: int = 50,
                   domain: str = "", status: str = "") -> str:
    """Get email forwarding logs with optional filters."""
    query = {"page": str(page), "limit": str(min(limit, 100))}
    if domain:
        query["domain"] = domain
    if status:
        query["status"] = status
    return _arcrelay_request("GET", "/api/logs", api_key=api_key, query=query)


def email_block_sender(api_key: str, sender_pattern: str,
                       domain_id: str = "") -> str:
    """Block a sender by email address or @domain pattern."""
    body: dict = {"sender_pattern": sender_pattern, "action": "block"}
    if domain_id:
        body["domain_id"] = domain_id
    return _arcrelay_request("POST", "/api/sender-rules", api_key=api_key, body=body)


def email_get_analytics(api_key: str) -> str:
    """Get email analytics: volume, rejection rate, top domains."""
    return _arcrelay_request("GET", "/api/analytics", api_key=api_key)


# ── Registration ───────────────────────────────────────────────────────────


def register(registry: ToolRegistry):
    # Public tools
    registry.register(
        name="email_check_dmarc",
        description="Check DMARC, SPF, and MX records for a domain via ARC-Relay.",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain to check (e.g. 'example.com')"},
            },
            "required": ["domain"],
        },
        handler=email_check_dmarc,
    )
    registry.register(
        name="email_check_health",
        description="Get email health score (0-100) and recommendations for a domain via ARC-Relay.",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain to check"},
            },
            "required": ["domain"],
        },
        handler=email_check_health,
    )

    # Authenticated tools
    registry.register(
        name="email_list_domains",
        description="List all email domains for the authenticated ARC-Relay user.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key (ar_live_...)"},
            },
            "required": ["api_key"],
        },
        handler=email_list_domains,
    )
    registry.register(
        name="email_add_domain",
        description="Add a domain to the ARC-Relay account for email forwarding.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "domain": {"type": "string", "description": "Domain to add (e.g. 'mydomain.com')"},
            },
            "required": ["api_key", "domain"],
        },
        handler=email_add_domain,
    )
    registry.register(
        name="email_verify_domain",
        description="Verify DNS records (TXT token + MX) for a domain in ARC-Relay.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "domain_id": {"type": "string", "description": "Domain ID (UUID)"},
            },
            "required": ["api_key", "domain_id"],
        },
        handler=email_verify_domain,
    )
    registry.register(
        name="email_list_aliases",
        description="List all email aliases for a domain in ARC-Relay.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "domain_id": {"type": "string", "description": "Domain ID (UUID)"},
            },
            "required": ["api_key", "domain_id"],
        },
        handler=email_list_aliases,
    )
    registry.register(
        name="email_create_alias",
        description="Create an email alias that forwards to a destination address.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "domain_id": {"type": "string", "description": "Domain ID (UUID)"},
                "alias": {"type": "string", "description": "Alias name (e.g. 'support')"},
                "forward_to": {"type": "string", "description": "Destination email address"},
            },
            "required": ["api_key", "domain_id", "alias", "forward_to"],
        },
        handler=email_create_alias,
    )
    registry.register(
        name="email_get_logs",
        description="Get email forwarding logs from ARC-Relay with optional filters.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "page": {"type": "integer", "description": "Page number (default: 1)"},
                "limit": {"type": "integer", "description": "Results per page (default: 50, max: 100)"},
                "domain": {"type": "string", "description": "Filter by domain name"},
                "status": {"type": "string", "description": "Filter by status (delivered, rejected, failed)"},
            },
            "required": ["api_key"],
        },
        handler=email_get_logs,
    )
    registry.register(
        name="email_block_sender",
        description="Block a sender by email or @domain pattern in ARC-Relay.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
                "sender_pattern": {"type": "string", "description": "Email (user@example.com) or domain pattern (@example.com)"},
                "domain_id": {"type": "string", "description": "Optional: restrict rule to this domain ID"},
            },
            "required": ["api_key", "sender_pattern"],
        },
        handler=email_block_sender,
    )
    registry.register(
        name="email_get_analytics",
        description="Get email analytics from ARC-Relay: volume, rejection rate, top domains.",
        parameters={
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "ARC-Relay API key"},
            },
            "required": ["api_key"],
        },
        handler=email_get_analytics,
    )
