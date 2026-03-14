"""
Broker adapters for trade execution.

Supports paper trading (default) and real broker integration.

Broker modes:
  - PaperBroker              — simulated fills at market price
  - TradierBroker            — real equity execution via Tradier API
  - RobinhoodBroker          — FULL: stocks + options + crypto (user/pass)
  - RobinhoodCryptoAPIBroker — crypto-only via API key
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

from forge.trading.portfolio import get_portfolio_manager
from forge.trading.providers import get_provider, get_provider_from_config

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

        # Get current price for fill — try configured provider, fall back to yfinance
        provider = get_provider_from_config(self._provider_name)
        quote = provider.get_quote(ticker)
        fill_price = price if (order_type == "limit" and price) else quote.price

        if fill_price <= 0 and self._provider_name != "yfinance":
            log.warning("Primary provider %s returned 0 for %s, falling back to yfinance",
                        self._provider_name, ticker)
            fallback = get_provider("yfinance")
            quote = fallback.get_quote(ticker)
            fill_price = price if (order_type == "limit" and price) else quote.price

        if fill_price <= 0:
            return {"error": f"Could not get price for {ticker} (tried {self._provider_name} + yfinance)"}

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
        import urllib.parse
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
    """Full Robinhood broker via robin_stocks (stocks + options + crypto)."""

    @property
    def name(self) -> str:
        return "robinhood"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        provider = get_provider_from_config("robinhood")
        if hasattr(provider, "order_stock"):
            return provider.order_stock(ticker, side, quantity, order_type, price)
        return {"error": "Robinhood legacy provider not configured"}

    def place_option_order(self, ticker: str, expiry: str, strike: float,
                           option_type: str, side: str, quantity: int,
                           order_type: str = "market", price: float | None = None) -> dict:
        """Place an options order (puts, calls, etc.)."""
        provider = get_provider_from_config("robinhood")
        if hasattr(provider, "order_option"):
            return provider.order_option(
                ticker, expiry, strike, option_type, side, quantity, order_type, price,
            )
        return {"error": "Robinhood legacy provider not configured for options"}

    def place_crypto_order(self, symbol: str, side: str, quantity: float,
                           order_type: str = "market", price: float | None = None) -> dict:
        """Place a crypto order."""
        provider = get_provider_from_config("robinhood")
        if hasattr(provider, "order_crypto"):
            return provider.order_crypto(symbol, side, quantity, order_type, price)
        return {"error": "Robinhood legacy provider not configured for crypto"}

    def cancel_order(self, order_id: str) -> bool:
        return False


class RobinhoodCryptoAPIBroker(BrokerAdapter):
    """Crypto-only broker via Robinhood Crypto API (API key)."""

    @property
    def name(self) -> str:
        return "robinhood-crypto"

    def place_order(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        provider = get_provider_from_config("robinhood-crypto")
        if hasattr(provider, "order_crypto"):
            return provider.order_crypto(ticker, side, quantity, order_type, price)
        return {"error": "Robinhood Crypto API provider not configured"}

    def place_crypto_order(self, ticker: str, side: str, quantity: float,
                           order_type: str = "market", price: float | None = None) -> dict:
        return self.place_order(ticker, side, quantity, order_type, price)

    def cancel_order(self, order_id: str) -> bool:
        return False


# ── Broker Factory ───────────────────────────────────────────────────────────

_broker: BrokerAdapter | None = None
_broker_lock = threading.Lock()


def _build_broker(provider_name: str, *, allow_tradier_fallback: bool = False) -> BrokerAdapter:
    from forge.config import (
        TRADING_PAPER_MODE,
        TRADING_TRADIER_API_KEY,
        TRADING_TRADIER_ACCOUNT_ID,
        TRADING_TRADIER_SANDBOX,
        TRADING_ROBINHOOD_USER,
        TRADING_ROBINHOOD_PASS,
        TRADING_ROBINHOOD_API_KEY,
        TRADING_ROBINHOOD_API_SECRET,
    )

    if TRADING_PAPER_MODE:
        return PaperBroker(provider_name=provider_name)
    if provider_name == "robinhood" and TRADING_ROBINHOOD_USER and TRADING_ROBINHOOD_PASS:
        return RobinhoodBroker()
    if provider_name == "robinhood-crypto" and TRADING_ROBINHOOD_API_KEY and TRADING_ROBINHOOD_API_SECRET:
        return RobinhoodCryptoAPIBroker()
    if provider_name == "tradier" and TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID:
        return TradierBroker(
            api_key=TRADING_TRADIER_API_KEY,
            account_id=TRADING_TRADIER_ACCOUNT_ID,
            sandbox=TRADING_TRADIER_SANDBOX,
        )
    if allow_tradier_fallback and TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID:
        return TradierBroker(
            api_key=TRADING_TRADIER_API_KEY,
            account_id=TRADING_TRADIER_ACCOUNT_ID,
            sandbox=TRADING_TRADIER_SANDBOX,
        )
    return PaperBroker(provider_name=provider_name or "yfinance")


def get_broker(provider_name: str = "") -> BrokerAdapter:
    global _broker
    if provider_name:
        return _build_broker(provider_name)

    with _broker_lock:
        if _broker is None:
            from forge.config import TRADING_DEFAULT_PROVIDER

            _broker = _build_broker(TRADING_DEFAULT_PROVIDER, allow_tradier_fallback=True)
        return _broker
