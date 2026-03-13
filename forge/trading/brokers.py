"""
Broker adapters for trade execution.

Supports paper trading (default) and real broker integration.
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

from forge.trading.portfolio import get_portfolio_manager
from forge.trading.providers import get_provider

log = logging.getLogger("forge.trading.brokers")


class BrokerAdapter(ABC):
    """Abstract broker for order execution."""

    @abstractmethod
    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        """Place an order. Returns order result dict."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Broker identifier."""


class PaperBroker(BrokerAdapter):
    """Simulated broker — fills immediately at current market price."""

    def __init__(self, provider_name: str = "yfinance"):
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return "paper"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        if side not in ("buy", "sell"):
            return {"error": "side must be 'buy' or 'sell'"}
        if quantity <= 0:
            return {"error": "quantity must be positive"}

        # Get current price for fill
        provider = get_provider(self._provider_name)
        quote = provider.get_quote(ticker)
        fill_price = price if (order_type == "limit" and price) else quote.price

        if fill_price <= 0:
            return {"error": f"Could not get price for {ticker}"}

        # Record order and update portfolio
        pm = get_portfolio_manager()
        order = pm.record_order(
            ticker=ticker, side=side, quantity=quantity,
            order_type=order_type, price=price,
            fill_price=fill_price, status="filled", broker="paper",
        )
        pm.update_position(ticker, quantity, fill_price, side)

        return {
            **order,
            "paper_mode": True,
            "message": f"Paper {side} {quantity} {ticker} @ ${fill_price:.2f}",
        }

    def cancel_order(self, order_id: str) -> bool:
        return False  # Paper orders fill immediately


class TradierBroker(BrokerAdapter):
    """Real broker via Tradier API."""

    def __init__(self, api_key: str, account_id: str, sandbox: bool = True):
        self._api_key = api_key
        self._account_id = account_id
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "tradier"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        import json
        import urllib.request
        base = "https://sandbox.tradier.com/v1" if self._sandbox else "https://api.tradier.com/v1"
        url = f"{base}/accounts/{self._account_id}/orders"

        params = {
            "class": "equity",
            "symbol": ticker,
            "side": side,
            "quantity": str(int(quantity)),
            "type": order_type,
            "duration": "day",
        }
        if order_type == "limit" and price:
            params["price"] = str(price)

        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self._api_key}")
        req.add_header("Accept", "application/json")

        import urllib.parse
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                order_data = result.get("order", {})
                return {
                    "order_id": str(order_data.get("id", "")),
                    "status": order_data.get("status", "submitted"),
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "broker": "tradier",
                    "paper_mode": False,
                }
        except Exception as e:
            return {"error": f"Tradier order failed: {e}"}

    def cancel_order(self, order_id: str) -> bool:
        try:
            import urllib.request
            base = "https://sandbox.tradier.com/v1" if self._sandbox else "https://api.tradier.com/v1"
            url = f"{base}/accounts/{self._account_id}/orders/{order_id}"
            req = urllib.request.Request(url, method="DELETE")
            req.add_header("Authorization", f"Bearer {self._api_key}")
            urllib.request.urlopen(req, timeout=15)
            return True
        except Exception:
            return False


class RobinhoodBroker(BrokerAdapter):
    """Crypto broker via robin_stocks."""

    @property
    def name(self) -> str:
        return "robinhood"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        provider = get_provider("robinhood")
        if not hasattr(provider, "order_crypto"):
            return {"error": "Robinhood provider not configured"}
        return provider.order_crypto(ticker, side, quantity)

    def cancel_order(self, order_id: str) -> bool:
        return False


# ── Broker Factory ───────────────────────────────────────────────────────────

_broker: BrokerAdapter | None = None
_broker_lock = threading.Lock()


def get_broker() -> BrokerAdapter:
    global _broker
    with _broker_lock:
        if _broker is None:
            from forge.config import (
                TRADING_PAPER_MODE, TRADING_DEFAULT_PROVIDER,
                TRADING_TRADIER_API_KEY, TRADING_TRADIER_ACCOUNT_ID,
                TRADING_TRADIER_SANDBOX,
            )
            if TRADING_PAPER_MODE:
                _broker = PaperBroker(provider_name=TRADING_DEFAULT_PROVIDER)
            elif TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID:
                _broker = TradierBroker(
                    api_key=TRADING_TRADIER_API_KEY,
                    account_id=TRADING_TRADIER_ACCOUNT_ID,
                    sandbox=TRADING_TRADIER_SANDBOX,
                )
            else:
                _broker = PaperBroker(provider_name=TRADING_DEFAULT_PROVIDER)
        return _broker
