"""
Tests for the Trading module — PCR calculation, providers, engine, tools, and endpoints.
"""
import json
import os
import sys
import time
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.trading.providers import (
    OptionRow, OptionsChainResult, Quote, YFinanceProvider, TradierProvider,
)
from forge.trading.engine import (
    calculate_pcr, classify_sentiment, TradingEngine, PRESET_TICKERS,
    ALL_PRESET_TICKERS, PCRResult,
)


# ── PCR Calculation ──────────────────────────────────────────────────────────

class TestPCRCalculation:
    def test_basic_pcr(self):
        chain = OptionsChainResult(
            ticker="SPY", expiry="2024-03-15",
            calls=[
                OptionRow(strike=500, last=5.0, bid=4.9, ask=5.1, volume=1000, open_interest=5000, option_type="call"),
                OptionRow(strike=510, last=2.0, bid=1.9, ask=2.1, volume=500, open_interest=3000, option_type="call"),
            ],
            puts=[
                OptionRow(strike=490, last=3.0, bid=2.9, ask=3.1, volume=800, open_interest=4000, option_type="put"),
                OptionRow(strike=480, last=1.5, bid=1.4, ask=1.6, volume=400, open_interest=2000, option_type="put"),
            ],
            timestamp=time.time(),
        )
        result = calculate_pcr(chain)
        assert result.ticker == "SPY"
        assert result.put_vol == 1200  # 800 + 400
        assert result.call_vol == 1500  # 1000 + 500
        assert result.put_oi == 6000
        assert result.call_oi == 8000
        assert result.vol_ratio == round(1200 / 1500, 4)
        assert result.oi_ratio == round(6000 / 8000, 4)

    def test_pcr_zero_call_volume(self):
        chain = OptionsChainResult(
            ticker="TEST", expiry="2024-03-15",
            calls=[OptionRow(strike=100, last=1, bid=1, ask=1, volume=0, open_interest=0, option_type="call")],
            puts=[OptionRow(strike=90, last=1, bid=1, ask=1, volume=500, open_interest=100, option_type="put")],
            timestamp=time.time(),
        )
        result = calculate_pcr(chain)
        assert result.vol_ratio is None
        assert result.oi_ratio is None

    def test_pcr_empty_chain(self):
        chain = OptionsChainResult(ticker="EMPTY", expiry="2024-03-15", timestamp=time.time())
        result = calculate_pcr(chain)
        assert result.vol_ratio is None
        assert result.oi_ratio is None
        assert result.put_vol == 0
        assert result.call_vol == 0

    def test_pcr_to_dict(self):
        chain = OptionsChainResult(
            ticker="SPY", expiry="2024-03-15",
            calls=[OptionRow(strike=500, last=5, bid=5, ask=5, volume=1000, open_interest=5000, option_type="call")],
            puts=[OptionRow(strike=490, last=3, bid=3, ask=3, volume=1500, open_interest=7000, option_type="put")],
            timestamp=1000.0,
        )
        result = calculate_pcr(chain)
        d = result.to_dict()
        assert d["ticker"] == "SPY"
        assert d["expiry"] == "2024-03-15"
        assert "vol_ratio" in d
        assert "sentiment" in d


# ── Sentiment Classification ────────────────────────────────────────────────

class TestSentimentClassification:
    def test_bearish(self):
        assert classify_sentiment(1.5, 1.3) == "bearish"
        assert classify_sentiment(1.21, None) == "bearish"

    def test_bullish(self):
        assert classify_sentiment(0.5, 0.6) == "bullish"
        assert classify_sentiment(0.69, None) == "bullish"

    def test_neutral(self):
        assert classify_sentiment(1.0, 1.0) == "neutral"
        assert classify_sentiment(0.7, None) == "neutral"
        assert classify_sentiment(1.2, None) == "neutral"

    def test_none_values(self):
        assert classify_sentiment(None, None) == "neutral"
        assert classify_sentiment(None, 1.5) == "bearish"
        assert classify_sentiment(None, 0.5) == "bullish"


# ── Preset Tickers ───────────────────────────────────────────────────────────

class TestPresetTickers:
    def test_categories_exist(self):
        assert "indices" in PRESET_TICKERS
        assert "etfs" in PRESET_TICKERS
        assert "sectors" in PRESET_TICKERS
        assert "volatility" in PRESET_TICKERS

    def test_all_tickers_populated(self):
        assert len(ALL_PRESET_TICKERS) == 20

    def test_key_tickers_present(self):
        assert "SPY" in ALL_PRESET_TICKERS
        assert "QQQ" in ALL_PRESET_TICKERS
        assert "^VIX" in ALL_PRESET_TICKERS
        assert "^SPX" in ALL_PRESET_TICKERS


# ── Trading Engine ───────────────────────────────────────────────────────────

class TestTradingEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return TradingEngine(data_dir=tmp_path)

    def test_get_preset_tickers(self, engine):
        tickers = engine.get_preset_tickers()
        assert isinstance(tickers, dict)
        assert "etfs" in tickers

    def test_get_all_tickers(self, engine):
        tickers = engine.get_all_tickers()
        assert "SPY" in tickers
        assert len(tickers) == 20

    def test_set_alert(self, engine):
        alert = engine.set_alert("SPY", "vol_ratio", 1.2, "above")
        assert alert.ticker == "SPY"
        assert alert.metric == "vol_ratio"
        assert alert.threshold == 1.2
        assert alert.direction == "above"
        assert alert.alert_id

    def test_get_alerts(self, engine):
        engine.set_alert("SPY", "vol_ratio", 1.2, "above")
        engine.set_alert("QQQ", "oi_ratio", 0.7, "below")
        alerts = engine.get_alerts()
        assert len(alerts) == 2

    def test_remove_alert(self, engine):
        alert = engine.set_alert("SPY", "vol_ratio", 1.2, "above")
        assert engine.remove_alert(alert.alert_id)
        assert len(engine.get_alerts()) == 0

    def test_remove_nonexistent_alert(self, engine):
        assert not engine.remove_alert("nonexistent")

    def test_history_recording(self, engine):
        pcr = PCRResult(
            ticker="SPY", expiry="2024-03-15",
            vol_ratio=1.1, oi_ratio=0.9,
            put_vol=1000, call_vol=900,
            put_oi=5000, call_oi=5500,
            sentiment="neutral", timestamp=time.time(),
        )
        engine._record_history(pcr)
        history = engine.get_history("SPY", "2024-03-15")
        assert len(history) == 1
        assert history[0]["ticker"] == "SPY"

    def test_history_rolling_limit(self, engine):
        for i in range(110):
            pcr = PCRResult(
                ticker="SPY", expiry="2024-03-15",
                vol_ratio=1.0 + i * 0.01, oi_ratio=1.0,
                put_vol=1000, call_vol=1000,
                put_oi=5000, call_oi=5000,
                sentiment="neutral", timestamp=time.time(),
            )
            engine._record_history(pcr)
        history = engine.get_history("SPY", "2024-03-15")
        assert len(history) == 100

    def test_save_and_load_history(self, engine):
        pcr = PCRResult(
            ticker="SPY", expiry="2024-03-15",
            vol_ratio=1.1, oi_ratio=0.9,
            put_vol=1000, call_vol=900,
            put_oi=5000, call_oi=5500,
            sentiment="neutral", timestamp=time.time(),
        )
        engine._record_history(pcr)
        engine.save_history()

        # Create new engine from same dir
        engine2 = TradingEngine(data_dir=engine._data_dir)
        history = engine2.get_history("SPY", "2024-03-15")
        assert len(history) == 1

    def test_subscribe_unsubscribe(self, engine):
        q = engine.subscribe()
        assert q is not None
        engine.unsubscribe(q)

    def test_stop(self, engine):
        engine.stop()
        assert engine._alert_stop.is_set()


# ── Provider Data Models ─────────────────────────────────────────────────────

class TestProviderModels:
    def test_option_row_to_dict(self):
        row = OptionRow(strike=500, last=5.0, bid=4.9, ask=5.1,
                        volume=1000, open_interest=5000, option_type="call")
        d = row.to_dict()
        assert d["strike"] == 500
        assert d["volume"] == 1000

    def test_options_chain_to_dict(self):
        chain = OptionsChainResult(
            ticker="SPY", expiry="2024-03-15",
            calls=[OptionRow(strike=500, last=5, bid=5, ask=5, volume=1000, open_interest=5000, option_type="call")],
            puts=[],
            timestamp=1000.0,
        )
        d = chain.to_dict()
        assert d["ticker"] == "SPY"
        assert len(d["calls"]) == 1
        assert len(d["puts"]) == 0

    def test_yfinance_provider_name(self):
        p = YFinanceProvider()
        assert p.name == "yfinance"

    def test_tradier_provider_name(self):
        p = TradierProvider(api_key="test", sandbox=True)
        assert p.name == "tradier"


# ── Portfolio Manager ────────────────────────────────────────────────────────

class TestPortfolioManager:
    @pytest.fixture
    def pm(self, tmp_path):
        from forge.trading.portfolio import PortfolioManager
        return PortfolioManager(str(tmp_path / "test_portfolio.db"))

    def test_empty_portfolio(self, pm):
        positions = pm.get_positions()
        assert positions == []

    def test_open_position(self, pm):
        pos = pm.update_position("SPY", 10, 500.0, "buy")
        assert pos.ticker == "SPY"
        assert pos.quantity == 10
        assert pos.avg_price == 500.0

    def test_add_to_position(self, pm):
        pm.update_position("SPY", 10, 500.0, "buy")
        pos = pm.update_position("SPY", 5, 510.0, "buy")
        assert pos.quantity == 15
        expected_avg = (500.0 * 10 + 510.0 * 5) / 15
        assert abs(pos.avg_price - expected_avg) < 0.01

    def test_close_position(self, pm):
        pm.update_position("SPY", 10, 500.0, "buy")
        pm.update_position("SPY", 10, 520.0, "sell")
        positions = pm.get_positions()
        assert len(positions) == 0
        # Realized P&L should be (520 - 500) * 10 = 200
        assert pm.get_realized_pnl() == 200.0

    def test_partial_close(self, pm):
        pm.update_position("SPY", 10, 500.0, "buy")
        pm.update_position("SPY", 5, 520.0, "sell")
        positions = pm.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 5
        assert pm.get_realized_pnl() == 100.0  # (520 - 500) * 5

    def test_record_order(self, pm):
        order = pm.record_order("SPY", "buy", 10, fill_price=500.0)
        assert order["ticker"] == "SPY"
        assert order["order_id"]

    def test_get_orders(self, pm):
        pm.record_order("SPY", "buy", 10, fill_price=500.0)
        pm.record_order("QQQ", "sell", 5, fill_price=400.0)
        orders = pm.get_orders()
        assert len(orders) == 2

    def test_summary(self, pm):
        pm.update_position("SPY", 10, 500.0, "buy")
        summary = pm.get_summary()
        assert summary["position_count"] == 1
        assert summary["realized_pnl"] == 0
        assert len(summary["positions"]) == 1

    def test_reset(self, pm):
        pm.update_position("SPY", 10, 500.0, "buy")
        pm.reset()
        assert len(pm.get_positions()) == 0


# ── Brokers ──────────────────────────────────────────────────────────────────

class TestPaperBroker:
    def test_invalid_side(self):
        from forge.trading.brokers import PaperBroker
        broker = PaperBroker()
        result = broker.place_order("SPY", "invalid", 10)
        assert "error" in result

    def test_negative_quantity(self):
        from forge.trading.brokers import PaperBroker
        broker = PaperBroker()
        result = broker.place_order("SPY", "buy", -5)
        assert "error" in result

    def test_broker_name(self):
        from forge.trading.brokers import PaperBroker
        broker = PaperBroker()
        assert broker.name == "paper"

    def test_uses_configured_provider_for_quotes(self, monkeypatch):
        from forge.trading import brokers as broker_mod
        from forge.trading.brokers import PaperBroker
        from forge.trading.providers import Quote

        class DummyProvider:
            def get_quote(self, ticker):
                assert ticker == "BTC"
                return Quote(ticker=ticker, price=42000.0, timestamp=time.time())

        class DummyPortfolio:
            def record_order(self, **kwargs):
                return {
                    "order_id": "paper-1",
                    "ticker": kwargs["ticker"],
                    "side": kwargs["side"],
                    "quantity": kwargs["quantity"],
                    "order_type": kwargs["order_type"],
                    "fill_price": kwargs["fill_price"],
                    "status": kwargs["status"],
                    "broker": kwargs["broker"],
                }

            def update_position(self, *args, **kwargs):
                return None

        monkeypatch.setattr(broker_mod, "get_provider_from_config", lambda name="": DummyProvider())
        monkeypatch.setattr(broker_mod, "get_portfolio_manager", lambda: DummyPortfolio())

        result = PaperBroker(provider_name="robinhood").place_order("BTC", "buy", 0.01)
        assert result["paper_mode"] is True
        assert result["fill_price"] == 42000.0


# ── Trading Tools Registration ───────────────────────────────────────────────

class TestTradingTools:
    def test_register(self):
        from forge.tools.registry import ToolRegistry
        from forge.tools.trading import register
        reg = ToolRegistry()
        register(reg)
        tools = reg.list_tools()
        assert "fetch_pcr" in tools
        assert "analyze_sentiment" in tools
        assert "get_options_chain" in tools
        assert "set_alert" in tools
        assert "get_portfolio" in tools
        assert "execute_trade" in tools
        assert "get_market_quote" in tools

    def test_tool_count(self):
        from forge.tools.registry import ToolRegistry
        from forge.tools.trading import register
        reg = ToolRegistry()
        register(reg)
        assert len(reg.list_tools()) == 7


# ── Trading Category in Registry ─────────────────────────────────────────────

class TestTradingCategory:
    def test_trading_category_exists(self):
        from forge.tools.registry import TOOL_CATEGORIES
        assert "trading" in TOOL_CATEGORIES

    def test_trading_tools_in_category(self):
        from forge.tools.registry import TOOL_CATEGORIES
        trading_tools = TOOL_CATEGORIES["trading"]
        assert "fetch_pcr" in trading_tools
        assert "execute_trade" in trading_tools
        assert "get_market_quote" in trading_tools

    def test_resolve_trading_category(self):
        from forge.tools.registry import resolve_tools_for_step
        resolved = resolve_tools_for_step(["trading"])
        assert "fetch_pcr" in resolved
        assert "analyze_sentiment" in resolved
        assert "execute_trade" in resolved


# ── Flask Endpoints ──────────────────────────────────────────────────────────

class TestTradingEndpoints:
    @pytest.fixture
    def client(self):
        from forge.app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_config_includes_trading(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.get_json()
        assert "trading" in data["features"]

    def test_tickers_endpoint(self, client):
        r = client.get("/api/trading/tickers")
        assert r.status_code == 200
        data = r.get_json()
        assert "indices" in data
        assert "etfs" in data

    def test_trading_config_endpoint(self, client):
        r = client.get("/api/trading/config")
        assert r.status_code == 200
        data = r.get_json()
        assert "enabled" in data
        assert "default_provider" in data
        assert "providers" in data
        assert "readiness" in data
        assert "available" in data["providers"]["robinhood"]
        assert "issues" in data["providers"]["robinhood-crypto"]

    def test_alerts_empty(self, client):
        r = client.get("/api/trading/alerts")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_set_alert(self, client):
        r = client.post("/api/trading/alerts", json={
            "ticker": "SPY", "metric": "vol_ratio",
            "threshold": 1.2, "direction": "above",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["ticker"] == "SPY"
        assert data["alert_id"]

    def test_set_alert_validation(self, client):
        r = client.post("/api/trading/alerts", json={
            "ticker": "", "metric": "vol_ratio",
            "threshold": 1.2, "direction": "above",
        })
        assert r.status_code == 400

    def test_portfolio_endpoint(self, client):
        r = client.get("/api/trading/portfolio")
        assert r.status_code == 200

    def test_order_validation(self, client):
        r = client.post("/api/trading/order", json={
            "ticker": "", "side": "buy", "quantity": 0,
        })
        assert r.status_code == 400

    def test_order_dependency_error_returns_400(self, client, monkeypatch):
        from forge.trading import brokers as broker_mod

        class DummyBroker:
            name = "robinhood-crypto"

            def place_crypto_order(self, ticker, side, quantity):
                return {
                    "error": (
                        "RuntimeError: Robinhood Crypto API requires the optional package "
                        "'cryptography'. Install the trading extras and run The Forge from "
                        "that environment's Python."
                    )
                }

        monkeypatch.setattr(broker_mod, "get_broker", lambda: DummyBroker())

        r = client.post("/api/trading/order", json={
            "asset_type": "crypto",
            "ticker": "DOGE",
            "side": "buy",
            "quantity": 1,
        })
        assert r.status_code == 400
        data = r.get_json()
        assert "cryptography" in data["error"]

    def test_orders_endpoint(self, client):
        r = client.get("/api/trading/orders")
        assert r.status_code == 200

    def test_history_endpoint(self, client):
        r = client.get("/api/trading/history/SPY")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ticker"] == "SPY"


# ── Position P&L Math ────────────────────────────────────────────────────────

class TestPositionPnL:
    def test_long_profit(self):
        from forge.trading.portfolio import Position
        pos = Position(ticker="SPY", quantity=10, avg_price=500, current_price=520, side="long")
        assert pos.unrealized_pnl == 200
        assert abs(pos.unrealized_pnl_pct - 4.0) < 0.01

    def test_long_loss(self):
        from forge.trading.portfolio import Position
        pos = Position(ticker="SPY", quantity=10, avg_price=500, current_price=480, side="long")
        assert pos.unrealized_pnl == -200

    def test_to_dict(self):
        from forge.trading.portfolio import Position
        pos = Position(ticker="SPY", quantity=10, avg_price=500, current_price=520, side="long")
        d = pos.to_dict()
        assert d["ticker"] == "SPY"
        assert d["market_value"] == 5200
        assert d["unrealized_pnl"] == 200


# ── Phase 1 Regression Tests (hardening f6c6412) ─────────────────────────────


class TestMarkToMarketEdgeCases:
    """Regression tests for mark-to-market with zero/negative quotes."""

    def test_zero_quote_treated_as_unavailable(self):
        """Quote=0 should NOT update current_price (treat as data unavailable)."""
        from forge.trading.portfolio import PortfolioManager
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm = PortfolioManager(f.name)
        pm.update_position("AAPL", 10, 150.0, "buy")

        # Price fetcher returns 0 — should be treated as unavailable
        zero_fetcher = lambda t: 0.0
        summary = pm.get_summary(price_fetcher=zero_fetcher)
        pos = summary["positions"][0]
        # current_price should stay at 0 (default), NOT be "updated" to 0
        assert pos["current_price"] == 0.0
        # unrealized P&L should reflect the unavailable price, not show a bogus loss
        assert pos["unrealized_pnl"] == -1500.0  # (0 - 150) * 10

    def test_negative_quote_treated_as_unavailable(self):
        """Negative quote should NOT update current_price."""
        from forge.trading.portfolio import PortfolioManager
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm = PortfolioManager(f.name)
        pm.update_position("TSLA", 5, 200.0, "buy")

        negative_fetcher = lambda t: -1.0
        summary = pm.get_summary(price_fetcher=negative_fetcher)
        pos = summary["positions"][0]
        assert pos["current_price"] == 0.0  # should not be -1.0

    def test_valid_quote_updates_price(self):
        """Positive quote should update current_price normally."""
        from forge.trading.portfolio import PortfolioManager
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm = PortfolioManager(f.name)
        pm.update_position("MSFT", 10, 400.0, "buy")

        good_fetcher = lambda t: 420.0
        summary = pm.get_summary(price_fetcher=good_fetcher)
        pos = summary["positions"][0]
        assert pos["current_price"] == 420.0
        assert pos["unrealized_pnl"] == 200.0  # (420-400)*10

    def test_none_quote_treated_as_unavailable(self):
        """None return from fetcher should not crash."""
        from forge.trading.portfolio import PortfolioManager
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm = PortfolioManager(f.name)
        pm.update_position("GOOG", 2, 170.0, "buy")

        none_fetcher = lambda t: None
        summary = pm.get_summary(price_fetcher=none_fetcher)
        pos = summary["positions"][0]
        assert pos["current_price"] == 0.0

    def test_exception_in_fetcher_leaves_price_at_zero(self):
        """Exception in price_fetcher should leave current_price at 0."""
        from forge.trading.portfolio import PortfolioManager
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm = PortfolioManager(f.name)
        pm.update_position("AMZN", 3, 180.0, "buy")

        def broken_fetcher(t):
            raise ConnectionError("API down")

        summary = pm.get_summary(price_fetcher=broken_fetcher)
        pos = summary["positions"][0]
        assert pos["current_price"] == 0.0


class TestProviderReadiness:
    """Regression tests for trading provider/broker readiness checks."""

    def test_readiness_disabled(self):
        """Trading disabled → unavailable."""
        from unittest.mock import patch
        with patch.dict(os.environ, {"FORGE_TRADING_ENABLED": "false"}):
            # Reload config to pick up env change
            import importlib
            import forge.config as cfg
            orig_enabled = cfg.TRADING_ENABLED
            cfg.TRADING_ENABLED = False
            try:
                from forge.trading import check_trading_readiness
                result = check_trading_readiness()
                assert result["state"] == "unavailable"
            finally:
                cfg.TRADING_ENABLED = orig_enabled

    def test_readiness_paper_mode(self):
        """Paper mode with yfinance → ready."""
        import forge.config as cfg
        orig = (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE, cfg.TRADING_DEFAULT_PROVIDER)
        cfg.TRADING_ENABLED = True
        cfg.TRADING_PAPER_MODE = True
        cfg.TRADING_DEFAULT_PROVIDER = "yfinance"
        try:
            from forge.trading import check_trading_readiness
            result = check_trading_readiness()
            assert result["state"] == "ready"
            assert result["broker"] == "paper"
        finally:
            cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE, cfg.TRADING_DEFAULT_PROVIDER = orig

    def test_readiness_tradier_partial_creds(self):
        """Tradier API key set but account_id missing → degraded."""
        import forge.config as cfg
        orig = (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
                cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID)
        cfg.TRADING_ENABLED = True
        cfg.TRADING_PAPER_MODE = False
        cfg.TRADING_TRADIER_API_KEY = "test-key-123"
        cfg.TRADING_TRADIER_ACCOUNT_ID = ""
        try:
            from forge.trading import check_trading_readiness
            result = check_trading_readiness()
            assert result["state"] == "degraded"
            assert result["broker"] == "paper"
            assert any("account_id" in issue.lower() for issue in result["issues"])
        finally:
            (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
             cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID) = orig

    def test_readiness_tradier_full_creds(self):
        """Tradier with full credentials → ready, broker=tradier."""
        import forge.config as cfg
        orig = (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
                cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID,
                cfg.TRADING_DEFAULT_PROVIDER)
        cfg.TRADING_ENABLED = True
        cfg.TRADING_PAPER_MODE = False
        cfg.TRADING_TRADIER_API_KEY = "test-key-123"
        cfg.TRADING_TRADIER_ACCOUNT_ID = "test-account-456"
        cfg.TRADING_DEFAULT_PROVIDER = "yfinance"
        try:
            from forge.trading import check_trading_readiness
            result = check_trading_readiness()
            assert result["state"] == "ready"
            assert result["broker"] == "tradier"
            assert result["issues"] == []
        finally:
            (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
             cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID,
             cfg.TRADING_DEFAULT_PROVIDER) = orig

    def test_readiness_no_broker_creds_falls_back(self):
        """No broker credentials, not paper mode → degraded with paper fallback."""
        import forge.config as cfg
        orig = (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
                cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID)
        cfg.TRADING_ENABLED = True
        cfg.TRADING_PAPER_MODE = False
        cfg.TRADING_TRADIER_API_KEY = ""
        cfg.TRADING_TRADIER_ACCOUNT_ID = ""
        try:
            from forge.trading import check_trading_readiness
            result = check_trading_readiness()
            assert result["state"] == "degraded"
            assert result["broker"] == "paper"
        finally:
            (cfg.TRADING_ENABLED, cfg.TRADING_PAPER_MODE,
             cfg.TRADING_TRADIER_API_KEY, cfg.TRADING_TRADIER_ACCOUNT_ID) = orig


    def test_readiness_robinhood_crypto_missing_dependency(self, monkeypatch):
        """Robinhood crypto without cryptography should be unavailable."""
        import forge.config as cfg
        import forge.trading as trading_mod

        orig = (
            cfg.TRADING_ENABLED,
            cfg.TRADING_PAPER_MODE,
            cfg.TRADING_DEFAULT_PROVIDER,
            cfg.TRADING_ROBINHOOD_API_KEY,
            cfg.TRADING_ROBINHOOD_API_SECRET,
        )
        cfg.TRADING_ENABLED = True
        cfg.TRADING_PAPER_MODE = False
        cfg.TRADING_DEFAULT_PROVIDER = "robinhood-crypto"
        cfg.TRADING_ROBINHOOD_API_KEY = "key"
        cfg.TRADING_ROBINHOOD_API_SECRET = "secret"
        monkeypatch.setattr(
            trading_mod,
            "get_provider_dependency_status",
            lambda provider: {
                "provider": provider,
                "available": False,
                "missing_dependencies": ["cryptography"],
                "issue": "Robinhood Crypto API requires the optional package 'cryptography'.",
            },
        )

        try:
            result = trading_mod.check_trading_readiness()
            assert result["state"] == "unavailable"
            assert any("cryptography" in issue for issue in result["issues"])
        finally:
            (
                cfg.TRADING_ENABLED,
                cfg.TRADING_PAPER_MODE,
                cfg.TRADING_DEFAULT_PROVIDER,
                cfg.TRADING_ROBINHOOD_API_KEY,
                cfg.TRADING_ROBINHOOD_API_SECRET,
            ) = orig


class TestProviderCaching:
    """Regression tests for provider singleton caching behavior."""

    def test_unconfigured_tradier_not_cached(self):
        """Tradier without API key should not be cached — so re-calling with
        real credentials gets a fresh instance."""
        from forge.trading.providers import get_provider, _providers
        # Clear cache
        _providers.pop("tradier", None)

        p1 = get_provider("tradier", api_key="")
        assert "tradier" not in _providers  # should NOT be cached

    def test_configured_tradier_is_cached(self):
        """Tradier with API key should be cached."""
        from forge.trading.providers import get_provider, _providers
        _providers.pop("tradier", None)

        p1 = get_provider("tradier", api_key="real-key-123", sandbox=True)
        assert "tradier" in _providers

        p2 = get_provider("tradier")
        assert p1 is p2  # same instance from cache

        # Clean up
        _providers.pop("tradier", None)

    def test_yfinance_always_cached(self):
        """YFinance provider should always be cached (no credentials needed)."""
        from forge.trading.providers import get_provider, _providers
        _providers.pop("yfinance", None)

        p1 = get_provider("yfinance")
        assert "yfinance" in _providers
        p2 = get_provider("yfinance")
        assert p1 is p2

        _providers.pop("yfinance", None)

    def test_partial_robinhood_not_cached(self):
        """Robinhood should not cache until both username and password exist."""
        from forge.trading.providers import get_provider, _providers
        _providers.pop("robinhood", None)

        get_provider("robinhood", username="user-only", password="")
        assert "robinhood" not in _providers

    def test_partial_robinhood_crypto_not_cached(self):
        """Robinhood crypto provider should not cache until key and secret exist."""
        from forge.trading.providers import get_provider, _providers
        _providers.pop("robinhood-crypto", None)

        get_provider("robinhood-crypto", api_key="key-only", api_secret="")
        assert "robinhood-crypto" not in _providers

    def test_configured_robinhood_crypto_is_cached(self):
        """Robinhood crypto provider should cache when fully configured."""
        from forge.trading.providers import get_provider, _providers
        _providers.pop("robinhood-crypto", None)

        p1 = get_provider("robinhood-crypto", api_key="key", api_secret="secret")
        assert "robinhood-crypto" in _providers
        p2 = get_provider("robinhood-crypto")
        assert p1 is p2

        _providers.pop("robinhood-crypto", None)


class TestTradingDependencyChecks:
    def test_missing_dependency_status(self, monkeypatch):
        import forge.trading_deps as deps

        def fake_find_spec(name):
            return None if name == "cryptography" else object()

        monkeypatch.setattr(deps.importlib.util, "find_spec", fake_find_spec)

        status = deps.get_provider_dependency_status("robinhood-crypto")
        assert status["available"] is False
        assert status["missing_dependencies"] == ["cryptography"]
        assert "cryptography" in status["issue"]


class TestConfiguredProviderSelection:
    def test_engine_supports_robinhood_crypto(self, monkeypatch, tmp_path):
        from forge.trading import engine as engine_mod

        class DummyProvider:
            pass

        dummy = DummyProvider()
        calls = []

        def fake_get_provider_from_config(name=""):
            calls.append(name)
            return dummy

        monkeypatch.setattr(engine_mod, "get_provider_from_config", fake_get_provider_from_config)

        engine = engine_mod.TradingEngine(data_dir=tmp_path)
        assert engine._get_provider("robinhood-crypto") is dummy
        assert calls == ["robinhood-crypto"]
