"""
API key authentication for the external agent marketplace.

Provides the @require_api_key decorator that validates X-API-Key header
(or Authorization: Bearer forge_xxx) and sets g.agent_id on the Flask
request context.
"""
from __future__ import annotations

import functools
import logging

from flask import g, jsonify, request

log = logging.getLogger("forge.toll.auth")


def _extract_api_key() -> str | None:
    """Extract API key from request headers.

    Supports:
      - X-API-Key: forge_xxx
      - Authorization: Bearer forge_xxx
    """
    # Try X-API-Key header first
    key = request.headers.get("X-API-Key", "").strip()
    if key:
        return key

    # Fall back to Authorization: Bearer
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token.startswith("forge_"):
            return token

    return None


def require_api_key(f):
    """Flask route decorator — validates API key and sets g.agent_id.

    Returns 401 if key is missing, invalid, or revoked.
    On success, sets:
      - g.agent_id   (str)  — the agent ID associated with the key
      - g.api_key    (str)  — the raw API key
      - g.owner_id   (str)  — the key's owner
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from forge.config import TOLL_DB_PATH
        from forge.toll.ledger import Ledger

        api_key = _extract_api_key()
        if not api_key:
            return jsonify({
                "error": "authentication_required",
                "message": "Provide API key via X-API-Key header or Authorization: Bearer",
            }), 401

        ledger = _get_auth_ledger()
        key_record = ledger.validate_api_key(api_key)
        if not key_record:
            return jsonify({
                "error": "invalid_api_key",
                "message": "API key is invalid or has been revoked",
            }), 401

        # Set request context
        g.agent_id = key_record.agent_id
        g.api_key = key_record.api_key
        g.owner_id = key_record.owner_id

        return f(*args, **kwargs)
    return decorated


# Shared ledger for auth — lazy initialized
_auth_ledger = None


def _get_auth_ledger():
    global _auth_ledger
    if _auth_ledger is None:
        from forge.config import TOLL_DB_PATH
        from forge.toll.ledger import Ledger
        _auth_ledger = Ledger(TOLL_DB_PATH)
    return _auth_ledger
