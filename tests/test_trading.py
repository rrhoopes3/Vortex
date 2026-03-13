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
