"""Flask Blueprint for trading API endpoints."""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, jsonify, request

from forge.trading import check_trading_readiness
from forge.trading.engine import get_engine
from forge.trading_deps import get_provider_dependency_status

log = logging.getLogger("forge.trading.endpoints")

trading_bp = Blueprint("trading", __name__, url_prefix="/api/trading")


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
    return jsonify(
        {
            "ticker": q.ticker,
            "price": q.price,
            "change": q.change,
            "change_pct": q.change_pct,
            "volume": q.volume,
            "timestamp": q.timestamp,
        }
    )


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


@trading_bp.route("/history/<ticker>")
def get_history(ticker: str):
    """Get PCR history for a ticker."""
    expiry = request.args.get("expiry", "").strip()
    records = get_engine().get_history(ticker, expiry)
    return jsonify({"ticker": ticker, "records": records})


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

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@trading_bp.route("/config")
def get_config():
    """Return trading config, readiness, and per-provider capability state."""
    from forge.config import (
        TRADING_DEFAULT_PROVIDER,
        TRADING_ENABLED,
        TRADING_PAPER_MODE,
        TRADING_ROBINHOOD_API_KEY,
        TRADING_ROBINHOOD_API_SECRET,
        TRADING_ROBINHOOD_PASS,
        TRADING_ROBINHOOD_USER,
        TRADING_TRADIER_ACCOUNT_ID,
        TRADING_TRADIER_API_KEY,
    )

    readiness = check_trading_readiness()
    rh_legacy = bool(TRADING_ROBINHOOD_USER and TRADING_ROBINHOOD_PASS)
    rh_crypto_api = bool(TRADING_ROBINHOOD_API_KEY and TRADING_ROBINHOOD_API_SECRET)
    tradier_configured = bool(TRADING_TRADIER_API_KEY)
    tradier_can_trade = bool(TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID)
    rh_legacy_deps = get_provider_dependency_status("robinhood")
    rh_crypto_deps = get_provider_dependency_status("robinhood-crypto")
    rh_legacy_ready = rh_legacy and rh_legacy_deps["available"]
    rh_crypto_ready = rh_crypto_api and rh_crypto_deps["available"]

    return jsonify(
        {
            "enabled": TRADING_ENABLED,
            "default_provider": TRADING_DEFAULT_PROVIDER,
            "paper_mode": TRADING_PAPER_MODE,
            "readiness": readiness,
            "providers": {
                "yfinance": {
                    "configured": True,
                    "available": True,
                    "missing_dependencies": [],
                    "issues": [],
                    "mode": "free",
                    "label": "Yahoo Finance (Free, Delayed)",
                    "capabilities": {
                        "stocks": {"quotes": True, "trade": False},
                        "options": {"chains": True, "trade": False},
                        "crypto": {"quotes": False, "trade": False},
                    },
                    "data_quality": "delayed ~15min",
                    "auth": "none",
                },
                "tradier": {
                    "configured": tradier_configured,
                    "available": True,
                    "missing_dependencies": [],
                    "issues": (
                        []
                        if tradier_can_trade
                        else (
                            ["Set FORGE_TRADIER_API_KEY to enable Tradier market data"]
                            if not tradier_configured
                            else [
                                "Set FORGE_TRADIER_ACCOUNT_ID to enable live Tradier order routing"
                            ]
                        )
                    ),
                    "mode": "sandbox" if not tradier_can_trade else "live",
                    "label": "Tradier" + (" (Sandbox)" if not tradier_can_trade else " (Live)"),
                    "capabilities": {
                        "stocks": {"quotes": tradier_configured, "trade": tradier_can_trade},
                        "options": {"chains": tradier_configured, "trade": tradier_can_trade},
                        "crypto": {"quotes": False, "trade": False},
                    },
                    "data_quality": "real-time",
                    "auth": "api_key",
                    "env_vars": ["FORGE_TRADIER_API_KEY", "FORGE_TRADIER_ACCOUNT_ID"],
                },
                "robinhood": {
                    "configured": rh_legacy,
                    "available": rh_legacy_deps["available"],
                    "missing_dependencies": rh_legacy_deps["missing_dependencies"],
                    "issues": (
                        ([] if rh_legacy else [
                            "Set FORGE_ROBINHOOD_USER and FORGE_ROBINHOOD_PASS to enable Robinhood"
                        ])
                        + ([rh_legacy_deps["issue"]] if rh_legacy_deps["issue"] else [])
                    ),
                    "mode": "legacy",
                    "label": "Robinhood (Full Access)",
                    "capabilities": {
                        "stocks": {"quotes": rh_legacy_ready, "trade": rh_legacy_ready},
                        "options": {"chains": rh_legacy_ready, "trade": rh_legacy_ready},
                        "crypto": {"quotes": rh_legacy_ready, "trade": rh_legacy_ready},
                    },
                    "data_quality": "real-time",
                    "auth": "username/password",
                    "env_vars": ["FORGE_ROBINHOOD_USER", "FORGE_ROBINHOOD_PASS"],
                },
                "robinhood-crypto": {
                    "configured": rh_crypto_api,
                    "available": rh_crypto_deps["available"],
                    "missing_dependencies": rh_crypto_deps["missing_dependencies"],
                    "issues": (
                        ([] if rh_crypto_api else [
                            "Set FORGE_ROBINHOOD_API_KEY and FORGE_ROBINHOOD_API_SECRET to enable Robinhood Crypto API"
                        ])
                        + ([rh_crypto_deps["issue"]] if rh_crypto_deps["issue"] else [])
                    ),
                    "mode": "api-key",
                    "label": "Robinhood Crypto API",
                    "capabilities": {
                        "stocks": {"quotes": False, "trade": False},
                        "options": {"chains": False, "trade": False},
                        "crypto": {"quotes": rh_crypto_ready, "trade": rh_crypto_ready},
                    },
                    "data_quality": "real-time",
                    "auth": "api_key",
                    "env_vars": [
                        "FORGE_ROBINHOOD_API_KEY",
                        "FORGE_ROBINHOOD_API_SECRET",
                    ],
                },
            },
        }
    )


@trading_bp.route("/provider", methods=["POST"])
def switch_provider():
    """Switch the active trading provider at runtime."""
    import forge.config as cfg
    from forge.trading import brokers as broker_mod

    data = request.get_json() or {}
    provider = data.get("provider", "").strip()
    valid = {"yfinance", "tradier", "robinhood", "robinhood-crypto"}
    if provider not in valid:
        return jsonify({"error": f"Unknown provider: {provider}. Valid: {sorted(valid)}"}), 400

    if provider == "tradier" and not cfg.TRADING_TRADIER_API_KEY:
        return jsonify({"error": "Cannot switch to Tradier; FORGE_TRADIER_API_KEY not set"}), 400
    if provider == "robinhood" and not (
        cfg.TRADING_ROBINHOOD_USER and cfg.TRADING_ROBINHOOD_PASS
    ):
        return jsonify({"error": "Cannot switch to Robinhood; credentials not set"}), 400
    if provider == "robinhood-crypto" and not (
        cfg.TRADING_ROBINHOOD_API_KEY and cfg.TRADING_ROBINHOOD_API_SECRET
    ):
        return jsonify({"error": "Cannot switch to Robinhood Crypto API; API key not set"}), 400

    dep_status = get_provider_dependency_status(provider)
    if not dep_status["available"]:
        return jsonify({"error": dep_status["issue"]}), 400

    cfg.TRADING_DEFAULT_PROVIDER = provider
    with broker_mod._broker_lock:
        broker_mod._broker = None

    log.info("Trading provider switched to: %s", provider)
    return jsonify({"status": "ok", "provider": provider})


@trading_bp.route("/portfolio")
def get_portfolio():
    """Get current portfolio positions and P&L."""
    try:
        from forge.trading.portfolio import get_portfolio_manager

        provider = request.args.get("provider", "").strip()
        pm = get_portfolio_manager()

        price_fetcher = None
        if provider:
            engine = get_engine()
            price_fetcher = lambda t: engine.get_quote(t, provider=provider).price

        return jsonify(pm.get_summary(price_fetcher=price_fetcher))
    except ImportError:
        return jsonify({"positions": [], "total_pnl": 0, "message": "Portfolio module available"})


@trading_bp.route("/order", methods=["POST"])
def place_order():
    """Place a trade order."""
    try:
        from forge.config import TRADING_DEFAULT_PROVIDER, TRADING_PAPER_MODE
        from forge.trading.brokers import get_broker

        data = request.get_json() or {}
        asset_type = data.get("asset_type", "stock").strip()
        ticker = data.get("ticker", "").strip()
        side = data.get("side", "").strip()
        quantity = float(data.get("quantity", 0))
        order_type = data.get("order_type", "market").strip()
        price = float(data.get("price", 0)) if data.get("price") else None

        if not ticker or not side or quantity <= 0:
            return jsonify({"error": "ticker, side, and positive quantity required"}), 400

        broker = get_broker()
        log.info(
            "Order: asset=%s ticker=%s side=%s qty=%s broker=%s provider=%s paper=%s",
            asset_type,
            ticker,
            side,
            quantity,
            broker.name,
            TRADING_DEFAULT_PROVIDER,
            TRADING_PAPER_MODE,
        )

        if asset_type == "option":
            expiry = data.get("expiry", "").strip()
            strike = float(data.get("strike", 0))
            option_type = data.get("option_type", "call").strip()
            if not expiry or strike <= 0:
                return jsonify({"error": "expiry and strike required for options"}), 400
            if not hasattr(broker, "place_option_order"):
                return jsonify({"error": f"Broker '{broker.name}' does not support options trading"}), 400
            result = broker.place_option_order(
                ticker, expiry, strike, option_type, side, int(quantity), order_type, price
            )
        elif asset_type == "crypto":
            if not hasattr(broker, "place_crypto_order"):
                result = broker.place_order(ticker, side, quantity, order_type, price)
            else:
                result = broker.place_crypto_order(ticker, side, quantity)
        else:
            result = broker.place_order(ticker, side, quantity, order_type, price)

        if "error" in result:
            log.warning("Order failed: %s", result)
            lower_error = str(result.get("error", "")).lower()
            status = 400 if (
                "requires the optional package" in lower_error or "not configured" in lower_error
            ) else 502
            return (
                jsonify(
                    {
                        **result,
                        "_debug": {
                            "broker": broker.name,
                            "provider": TRADING_DEFAULT_PROVIDER,
                            "paper_mode": TRADING_PAPER_MODE,
                            "asset_type": asset_type,
                            "ticker": ticker,
                        },
                    }
                ),
                status,
            )
        return jsonify(result)
    except Exception as e:
        log.exception("Order endpoint exception")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@trading_bp.route("/orders")
def get_orders():
    """Get order history."""
    try:
        from forge.trading.portfolio import get_portfolio_manager

        pm = get_portfolio_manager()
        return jsonify(pm.get_orders())
    except ImportError:
        return jsonify([])
