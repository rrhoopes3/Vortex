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
    """Get current portfolio positions and P&L.

    When a live crypto provider is active, syncs real holdings from the
    brokerage so the portfolio reflects the actual account state.
    """
    try:
        from forge.config import TRADING_DEFAULT_PROVIDER, TRADING_PAPER_MODE
        from forge.trading.portfolio import get_portfolio_manager
        from forge.trading.providers import get_provider_from_config, RobinhoodCryptoAPIProvider

        provider_name = request.args.get("provider", "").strip()
        pm = get_portfolio_manager()

        # In live mode with a crypto provider, sync holdings from the brokerage
        effective_provider = provider_name or TRADING_DEFAULT_PROVIDER
        log.debug("Portfolio sync check: paper=%s, provider=%s", TRADING_PAPER_MODE, effective_provider)
        if not TRADING_PAPER_MODE and effective_provider in ("robinhood-crypto",):
            try:
                provider = get_provider_from_config(provider_name)
                if isinstance(provider, RobinhoodCryptoAPIProvider):
                    holdings = provider.get_holdings()
                    log.info("Synced %d holdings from Robinhood", len(holdings) if holdings else 0)
                    if holdings:
                        _sync_holdings_to_portfolio(pm, holdings, provider)
                else:
                    log.warning("Provider is %s, not RobinhoodCryptoAPIProvider", type(provider).__name__)
            except Exception as e:
                log.warning("Failed to sync live holdings: %s", e)

        price_fetcher = None
        if provider_name:
            engine = get_engine()
            price_fetcher = lambda t: engine.get_quote(t, provider=provider_name).price

        summary = pm.get_summary(price_fetcher=price_fetcher)
        log.info("Portfolio summary: %d positions, pnl=%s", summary.get("position_count", 0), summary.get("total_pnl", 0))
        return jsonify(summary)
    except ImportError:
        return jsonify({"positions": [], "total_pnl": 0, "message": "Portfolio module available"})


def _sync_holdings_to_portfolio(pm, holdings: list[dict], provider) -> None:
    """Sync live brokerage holdings into the local portfolio DB."""
    import time as _time
    for h in holdings:
        log.info("Raw holding: %s", {k: v for k, v in h.items() if k not in ("id",)})
        code = h.get("asset_code", "") or h.get("currency", {}).get("code", "")
        qty_str = h.get("total_quantity", "") or h.get("quantity", "") or h.get("quantity_available_for_trading", "") or "0"
        quantity = float(qty_str)
        log.info("Parsed holding: code=%s qty=%s (from '%s')", code, quantity, qty_str)
        if not code or quantity <= 0:
            log.warning("Skipping holding: code=%s qty=%s", code, quantity)
            continue

        # Get cost basis for avg price
        cost_bases = h.get("cost_bases", [])
        if cost_bases:
            direct_cost = float(cost_bases[0].get("direct_cost_basis", 0) or 0)
            direct_qty = float(cost_bases[0].get("direct_quantity", 0) or 0)
            avg_price = direct_cost / direct_qty if direct_qty > 0 else 0
        else:
            avg_price = 0

        # Upsert into local DB — replace with live data
        with pm._lock:
            row = pm._conn.execute(
                "SELECT * FROM positions WHERE ticker = ?", (code,)
            ).fetchone()
            now = _time.time()
            if row is None:
                pm._conn.execute(
                    "INSERT INTO positions (ticker, quantity, avg_price, side, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (code, quantity, avg_price, "long", now),
                )
            else:
                pm._conn.execute(
                    "UPDATE positions SET quantity = ?, avg_price = ?, updated_at = ? WHERE ticker = ?",
                    (quantity, avg_price if avg_price > 0 else row["avg_price"], now, code),
                )
            pm._conn.commit()


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

        # Record successful live orders in local portfolio DB
        if not TRADING_PAPER_MODE and result.get("status") in ("submitted", "filled", "confirmed"):
            try:
                from forge.trading.portfolio import get_portfolio_manager
                from forge.trading.providers import get_provider_from_config
                pm = get_portfolio_manager()
                # Try to get fill price from quote
                fill_price = price
                if not fill_price:
                    try:
                        provider = get_provider_from_config()
                        q = provider.get_quote(ticker)
                        fill_price = q.price
                    except Exception:
                        fill_price = 0
                pm.record_order(
                    ticker=ticker, side=side, quantity=quantity,
                    order_type=order_type, price=price,
                    fill_price=fill_price,
                    status="filled", broker=broker.name,
                )
                if fill_price:
                    pm.update_position(ticker, quantity, fill_price, side)
                    log.info("Portfolio updated: %s %s %s @ %s", side, quantity, ticker, fill_price)
            except Exception as e:
                log.warning("Failed to record order in portfolio: %s", e)

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


@trading_bp.route("/crypto/history/<symbol>")
def get_crypto_history(symbol: str):
    """Get crypto price history for charting via yfinance."""
    timeframe = request.args.get("timeframe", "1D").strip()
    try:
        import yfinance as yf

        tf_map = {
            "1D": ("1d", "5m"),
            "1W": ("5d", "30m"),
            "1M": ("1mo", "1h"),
            "3M": ("3mo", "1d"),
        }
        period, interval = tf_map.get(timeframe, ("1d", "5m"))

        yf_symbol = f"{symbol.upper()}-USD"
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=period, interval=interval)

        if hist.empty:
            return jsonify({"symbol": symbol, "candles": [], "timeframe": timeframe})

        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                "time": idx.isoformat(),
                "open": round(float(row.get("Open", 0)), 4),
                "high": round(float(row.get("High", 0)), 4),
                "low": round(float(row.get("Low", 0)), 4),
                "close": round(float(row.get("Close", 0)), 4),
                "volume": int(row.get("Volume", 0) or 0),
            })

        return jsonify({"symbol": symbol, "candles": candles, "timeframe": timeframe})
    except Exception as e:
        log.warning("Crypto history failed for %s: %s", symbol, e)
        return jsonify({"symbol": symbol, "candles": [], "error": str(e)})


# ── Crypto Agent endpoints ───────────────────────────────────────────────────

@trading_bp.route("/agent/status")
def agent_status():
    """Get current agent state."""
    from forge.trading.crypto_agent import get_state
    return jsonify(get_state())


@trading_bp.route("/agent/logs")
def agent_logs():
    """Get recent agent log entries."""
    from forge.trading.crypto_agent import get_logs
    limit = int(request.args.get("limit", 50))
    return jsonify(get_logs(limit))


@trading_bp.route("/agent/start", methods=["POST"])
def agent_start():
    """Start the autonomous trading agent."""
    from forge.trading.crypto_agent import AgentConfig, start
    data = request.get_json() or {}
    config = AgentConfig(
        model=data.get("model", "grok-4.20-beta-0309-reasoning"),
        strategy=data.get("strategy", "manual"),
        ticker=data.get("ticker", "BTC"),
        max_position_usd=float(data.get("max_position_usd", 50)),
        interval_minutes=int(data.get("interval_minutes", 15)),
    )
    result = start(config)
    if "error" in result:
        return jsonify(result), 409
    return jsonify(result)


@trading_bp.route("/agent/stop", methods=["POST"])
def agent_stop():
    """Stop the trading agent."""
    from forge.trading.crypto_agent import stop
    result = stop()
    if "error" in result:
        return jsonify(result), 409
    return jsonify(result)


@trading_bp.route("/agent/decisions")
def agent_decisions():
    """Get persisted agent decision history for analysis."""
    from forge.trading.portfolio import get_portfolio_manager
    ticker = request.args.get("ticker", "").strip() or None
    limit = int(request.args.get("limit", 100))
    pm = get_portfolio_manager()
    rows = pm.get_decisions(ticker=ticker, limit=limit)
    return jsonify(rows)


# ── Polymarket Proxy ──────────────────────────────────────────────────────

import requests as _req

GAMMA_BASE = "https://gamma-api.polymarket.com"


@trading_bp.route("/polymarket/markets")
def poly_markets():
    """Proxy Polymarket Gamma API — fetch active markets."""
    params = {
        "active": "true",
        "closed": "false",
        "limit": request.args.get("limit", "30"),
        "offset": request.args.get("offset", "0"),
        "order": request.args.get("order", "volume24hr"),
        "ascending": "false",
    }
    tag = request.args.get("tag", "").strip()
    if tag:
        params["tag_slug"] = tag
    q = request.args.get("q", "").strip()
    if q:
        params["_q"] = q
    try:
        resp = _req.get(f"{GAMMA_BASE}/markets", params=params, timeout=10)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        log.warning("Polymarket fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502


@trading_bp.route("/polymarket/events")
def poly_events():
    """Proxy Polymarket Gamma API — fetch events (grouped markets)."""
    params = {
        "active": "true",
        "closed": "false",
        "limit": request.args.get("limit", "20"),
        "offset": request.args.get("offset", "0"),
        "order": request.args.get("order", "volume24hr"),
        "ascending": "false",
    }
    tag = request.args.get("tag", "").strip()
    if tag:
        params["tag_slug"] = tag
    try:
        resp = _req.get(f"{GAMMA_BASE}/events", params=params, timeout=10)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as e:
        log.warning("Polymarket events fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502


@trading_bp.route("/polymarket/market/<slug>")
def poly_market_detail(slug: str):
    """Proxy Polymarket Gamma API — fetch single market by slug."""
    try:
        resp = _req.get(f"{GAMMA_BASE}/markets", params={"slug": slug}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return jsonify(data[0] if data else {})
    except Exception as e:
        log.warning("Polymarket detail fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502


@trading_bp.route("/polymarket/event/<slug>")
def poly_event_detail(slug: str):
    """Fetch a Polymarket event by slug (with its markets)."""
    try:
        resp = _req.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        event = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
        # Also fetch markets for this event
        mresp = _req.get(
            f"{GAMMA_BASE}/markets",
            params={"event_slug": slug, "active": "true", "closed": "false"},
            timeout=10,
        )
        mresp.raise_for_status()
        markets = mresp.json() if isinstance(mresp.json(), list) else []
        return jsonify({"event": event, "markets": markets})
    except Exception as e:
        log.warning("Polymarket event fetch failed: %s", e)
        return jsonify({"error": str(e)}), 502


# ── Polymarket Agent endpoints ────────────────────────────────────────────────

@trading_bp.route("/polymarket/agent/status")
def poly_agent_status():
    from forge.trading.polymarket_agent import get_state
    return jsonify(get_state())


@trading_bp.route("/polymarket/agent/logs")
def poly_agent_logs():
    from forge.trading.polymarket_agent import get_logs
    limit = int(request.args.get("limit", 50))
    return jsonify(get_logs(limit))


@trading_bp.route("/polymarket/agent/start", methods=["POST"])
def poly_agent_start():
    from forge.trading.polymarket_agent import PolyAgentConfig, start
    data = request.get_json() or {}
    config = PolyAgentConfig(
        model=data.get("model", "grok-4.20-beta-0309-reasoning"),
        strategy=data.get("strategy", "analyst"),
        event_slug=data.get("event_slug", ""),
        event_url=data.get("event_url", ""),
        max_position_usd=float(data.get("max_position_usd", 50)),
        interval_minutes=int(data.get("interval_minutes", 15)),
        live_trading=bool(data.get("live_trading", False)),
        dry_run=bool(data.get("dry_run", True)),
    )
    if not config.event_slug:
        return jsonify({"error": "event_slug is required"}), 400
    result = start(config)
    if "error" in result:
        return jsonify(result), 409
    return jsonify(result)


@trading_bp.route("/polymarket/agent/stop", methods=["POST"])
def poly_agent_stop():
    from forge.trading.polymarket_agent import stop
    result = stop()
    if "error" in result:
        return jsonify(result), 409
    return jsonify(result)
