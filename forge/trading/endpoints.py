"""
Flask Blueprint for trading API endpoints.

All routes prefixed with /api/trading/.
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request, Response
from forge.trading.engine import get_engine

log = logging.getLogger("forge.trading.endpoints")

trading_bp = Blueprint("trading", __name__, url_prefix="/api/trading")


# ── PCR Data ─────────────────────────────────────────────────────────────────

@trading_bp.route("/pcr/<ticker>")
def get_pcr(ticker: str):
    """Get PCR ratios for a ticker."""
    expiry = request.args.get("expiry", "").strip()
    provider = request.args.get("provider", "").strip()
    try:
        result = get_engine().get_pcr(ticker, expiry=expiry, provider=provider)
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@trading_bp.route("/tickers")
def get_tickers():
    """Return preset tickers grouped by category."""
    return jsonify(get_engine().get_preset_tickers())


@trading_bp.route("/expirations/<ticker>")
def get_expirations(ticker: str):
    """Get available option expiration dates."""
    provider = request.args.get("provider", "").strip()
    exps = get_engine().get_expirations(ticker, provider=provider)
    return jsonify({"ticker": ticker, "expirations": exps})


@trading_bp.route("/chain/<ticker>")
def get_chain(ticker: str):
    """Get raw options chain data."""
    expiry = request.args.get("expiry", "").strip()
    provider = request.args.get("provider", "").strip()
    min_volume = int(request.args.get("min_volume", "0"))
    chain = get_engine().get_options_chain(ticker, expiry, provider, min_volume)
    return jsonify(chain.to_dict())


@trading_bp.route("/quote/<ticker>")
def get_quote(ticker: str):
    """Get current price quote."""
    provider = request.args.get("provider", "").strip()
    q = get_engine().get_quote(ticker, provider=provider)
    return jsonify({
        "ticker": q.ticker, "price": q.price,
        "change": q.change, "change_pct": q.change_pct,
        "volume": q.volume, "timestamp": q.timestamp,
    })


@trading_bp.route("/sentiment", methods=["POST"])
def analyze_sentiment():
    """Analyze PCR sentiment across multiple tickers."""
    data = request.get_json() or {}
    tickers = data.get("tickers", [])
    provider = data.get("provider", "")
    if not tickers:
        return jsonify({"error": "No tickers provided"}), 400
    result = get_engine().analyze_sentiment(tickers, provider=provider)
    return jsonify(result)


# ── Alerts ───────────────────────────────────────────────────────────────────

@trading_bp.route("/alerts")
def get_alerts():
    """List active alerts."""
    alerts = get_engine().get_alerts()
    return jsonify([a.to_dict() for a in alerts])


@trading_bp.route("/alerts", methods=["POST"])
def set_alert():
    """Create a new alert."""
    data = request.get_json() or {}
    ticker = data.get("ticker", "").strip()
    metric = data.get("metric", "vol_ratio").strip()
    threshold = float(data.get("threshold", 1.0))
    direction = data.get("direction", "above").strip()

    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    if metric not in ("vol_ratio", "oi_ratio"):
        return jsonify({"error": "metric must be vol_ratio or oi_ratio"}), 400
    if direction not in ("above", "below"):
        return jsonify({"error": "direction must be above or below"}), 400

    alert = get_engine().set_alert(ticker, metric, threshold, direction)
    return jsonify(alert.to_dict()), 201


@trading_bp.route("/alerts/<alert_id>", methods=["DELETE"])
def remove_alert(alert_id: str):
    """Remove an alert."""
    removed = get_engine().remove_alert(alert_id)
    if not removed:
        return jsonify({"error": "Alert not found"}), 404
    return jsonify({"status": "removed", "alert_id": alert_id})


# ── History ──────────────────────────────────────────────────────────────────

@trading_bp.route("/history/<ticker>")
def get_history(ticker: str):
    """Get PCR history for a ticker."""
    expiry = request.args.get("expiry", "").strip()
    records = get_engine().get_history(ticker, expiry)
    return jsonify({"ticker": ticker, "records": records})


# ── SSE Stream ───────────────────────────────────────────────────────────────

@trading_bp.route("/stream")
def trading_stream():
    """SSE stream for live PCR updates and alert triggers."""
    engine = get_engine()
    q = engine.subscribe()

    def generate():
        try:
            while True:
                msg = q.get()
                if msg is None:
                    break
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            engine.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── Config ───────────────────────────────────────────────────────────────────

@trading_bp.route("/config")
def get_config():
    """Return trading configuration."""
    from forge.config import (
        TRADING_ENABLED, TRADING_DEFAULT_PROVIDER, TRADING_PAPER_MODE,
        TRADING_TRADIER_API_KEY, TRADING_ROBINHOOD_USER,
    )
    return jsonify({
        "enabled": TRADING_ENABLED,
        "default_provider": TRADING_DEFAULT_PROVIDER,
        "paper_mode": TRADING_PAPER_MODE,
        "providers": {
            "yfinance": {"available": True, "configured": True},
            "tradier": {"available": True, "configured": bool(TRADING_TRADIER_API_KEY)},
            "robinhood": {"available": True, "configured": bool(TRADING_ROBINHOOD_USER)},
        },
    })


# ── Portfolio (Phase 3) ─────────────────────────────────────────────────────

@trading_bp.route("/portfolio")
def get_portfolio():
    """Get current portfolio positions and P&L."""
    try:
        from forge.trading.portfolio import get_portfolio_manager
        pm = get_portfolio_manager()
        return jsonify(pm.get_summary())
    except ImportError:
        return jsonify({"positions": [], "total_pnl": 0, "message": "Portfolio module available"})


@trading_bp.route("/order", methods=["POST"])
def place_order():
    """Place a trade order."""
    try:
        from forge.trading.brokers import get_broker
        data = request.get_json() or {}
        ticker = data.get("ticker", "").strip()
        side = data.get("side", "").strip()
        quantity = float(data.get("quantity", 0))
        order_type = data.get("order_type", "market").strip()
        price = float(data.get("price", 0)) if data.get("price") else None

        if not ticker or not side or quantity <= 0:
            return jsonify({"error": "ticker, side, and positive quantity required"}), 400

        broker = get_broker()
        result = broker.place_order(ticker, side, quantity, order_type, price)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "Trading brokers not yet configured"}), 501


@trading_bp.route("/orders")
def get_orders():
    """Get order history."""
    try:
        from forge.trading.portfolio import get_portfolio_manager
        pm = get_portfolio_manager()
        return jsonify(pm.get_orders())
    except ImportError:
        return jsonify([])
