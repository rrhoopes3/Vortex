import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_get_market_price_parses_mid_dict(monkeypatch):
    import forge.trading.polymarket_executor as pe

    class DummyClient:
        def get_midpoint(self, token_id):
            assert token_id == "token-1"
            return {"mid": "0.155"}

    monkeypatch.setattr(pe, "_get_client", lambda: DummyClient())

    assert pe.get_market_price("token-1") == pytest.approx(0.155)


def test_execute_market_order_dry_run_accepts_dict_midpoint(monkeypatch):
    import forge.trading.polymarket_executor as pe

    class DummyClient:
        def get_market(self, condition_id):
            assert condition_id == "cond-1"
            return {
                "tokens": [
                    {"outcome": "YES", "token_id": "yes-token"},
                    {"outcome": "NO", "token_id": "no-token"},
                ]
            }

        def get_midpoint(self, token_id):
            assert token_id == "yes-token"
            return {"mid": "0.155"}

    monkeypatch.setattr(pe, "_get_client", lambda: DummyClient())

    decision = pe.TradeDecision(action="BUY", side="YES", amount_usd=10.0, reason="edge")
    result = pe.execute_market_order(
        condition_id="cond-1",
        decision=decision,
        max_position_usd=50.0,
        dry_run=True,
    )

    assert result.success is True
    assert result.side == "YES"
    assert result.price == pytest.approx(0.155)
    assert result.shares == pytest.approx(10.0 / 0.155)
