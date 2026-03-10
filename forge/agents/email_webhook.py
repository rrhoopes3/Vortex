"""
Flask Blueprint for receiving ARC-Relay webhook events.

Validates HMAC-SHA256 signatures, then dispatches events to the EmailAgent.
"""
import hashlib
import hmac
import json
import logging

from flask import Blueprint, request, jsonify

log = logging.getLogger("forge.agents.webhook")

email_webhook_bp = Blueprint("email_webhook", __name__)

# Set by app.py on startup
_webhook_secret: str = ""
_email_agent = None


def configure(secret: str, agent):
    """Called by app.py to inject the secret and agent instance."""
    global _webhook_secret, _email_agent
    _webhook_secret = secret
    _email_agent = agent


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature from ARC-Relay."""
    if not _webhook_secret or not signature:
        return False
    expected = hmac.new(
        _webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    # ARC-Relay sends "sha256=<hex>"
    sig_hex = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, sig_hex)


@email_webhook_bp.route("/webhooks/arcrelay", methods=["POST"])
def receive_webhook():
    """Receive and validate ARC-Relay webhook events."""
    payload = request.get_data()
    signature = request.headers.get("X-ArcRelay-Signature", "")

    if not _verify_signature(payload, signature):
        log.warning("Webhook signature verification failed")
        return jsonify({"error": "Invalid signature"}), 401

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = event.get("type", "")
    if not event_type:
        return jsonify({"error": "Missing event type"}), 400

    log.info("Webhook received: %s", event_type)

    if _email_agent:
        _email_agent.handle_event(event)

    return jsonify({"status": "ok"})
