"""
Data provider adapters for options/market data.

Supported providers:
  - YFinanceProvider          — free, delayed data via yfinance
  - TradierProvider           — real-time via Tradier API v1
  - RobinhoodProvider         — full access via robin_stocks (stocks, options, crypto)
  - RobinhoodCryptoAPIProvider — crypto-only via Robinhood Crypto API key
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from forge.trading_deps import require_provider_dependencies

log = logging.getLogger("forge.trading.providers")


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class OptionRow:
    strike: float
    last: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    option_type: str  # "call" | "put"

    def to_dict(self) -> dict:
        return {
            "strike": self.strike,
            "last": self.last,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "option_type": self.option_type,
        }


@dataclass
class OptionsChainResult:
    ticker: str
    expiry: str
    calls: list[OptionRow] = field(default_factory=list)
    puts: list[OptionRow] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "expiry": self.expiry,
            "calls": [c.to_dict() for c in self.calls],
            "puts": [p.to_dict() for p in self.puts],
            "timestamp": self.timestamp,
        }


@dataclass
class Quote:
    ticker: str
    price: float
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    timestamp: float = 0.0


# ── Abstract Base ────────────────────────────────────────────────────────────

class DataProvider(ABC):
    """Abstract data provider for market/options data."""

    @abstractmethod
    def get_expirations(self, ticker: str) -> list[str]:
        """Return available option expiration dates as ISO strings."""

    @abstractmethod
    def get_options_chain(self, ticker: str, expiry: str) -> OptionsChainResult:
        """Fetch full options chain for a ticker + expiry."""

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """Get current price quote."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""


# ── YFinance Provider ────────────────────────────────────────────────────────

class YFinanceProvider(DataProvider):
    """Free delayed data via yfinance."""

    def __init__(self):
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "yfinance"

    def _get_ticker(self, symbol: str):
        import yfinance as yf
        return yf.Ticker(symbol)

    def get_expirations(self, ticker: str) -> list[str]:
        with self._lock:
            try:
                t = self._get_ticker(ticker)
                return list(t.options[:12])  # nearest 12
            except Exception as e:
                log.warning("yfinance expirations failed for %s: %s", ticker, e)
                return []

    def get_options_chain(self, ticker: str, expiry: str) -> OptionsChainResult:
        with self._lock:
            time.sleep(0.3)  # rate limit courtesy
            try:
                t = self._get_ticker(ticker)
                chain = t.option_chain(expiry)

                calls = []
                for _, row in chain.calls.iterrows():
                    calls.append(OptionRow(
                        strike=float(row.get("strike", 0)),
                        last=float(row.get("lastPrice", 0)),
                        bid=float(row.get("bid", 0)),
                        ask=float(row.get("ask", 0)),
                        volume=int(row.get("volume", 0) or 0),
                        open_interest=int(row.get("openInterest", 0) or 0),
                        option_type="call",
                    ))

                puts = []
                for _, row in chain.puts.iterrows():
                    puts.append(OptionRow(
                        strike=float(row.get("strike", 0)),
                        last=float(row.get("lastPrice", 0)),
                        bid=float(row.get("bid", 0)),
                        ask=float(row.get("ask", 0)),
                        volume=int(row.get("volume", 0) or 0),
                        open_interest=int(row.get("openInterest", 0) or 0),
                        option_type="put",
                    ))

                return OptionsChainResult(
                    ticker=ticker, expiry=expiry,
                    calls=calls, puts=puts,
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("yfinance chain failed for %s/%s: %s", ticker, expiry, e)
                return OptionsChainResult(ticker=ticker, expiry=expiry, timestamp=time.time())

    # Common crypto symbols that need -USD suffix for yfinance
    CRYPTO_SYMBOLS = {
        "BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "XRP", "ADA",
        "SHIB", "DOT", "MATIC", "UNI", "AAVE", "LTC", "ATOM", "NEAR",
        "APT", "ARB", "OP", "FIL", "ALGO", "XLM", "HBAR", "ICP",
    }

    def _yf_ticker(self, ticker: str) -> str:
        """Normalize ticker for yfinance — add -USD for crypto symbols."""
        upper = ticker.upper()
        if upper in self.CRYPTO_SYMBOLS and not upper.endswith("-USD"):
            return f"{upper}-USD"
        return ticker

    def get_quote(self, ticker: str) -> Quote:
        with self._lock:
            try:
                yf_sym = self._yf_ticker(ticker)
                t = self._get_ticker(yf_sym)
                info = t.fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                prev = float(getattr(info, "previous_close", price) or price)
                change = price - prev
                pct = (change / prev * 100) if prev else 0
                return Quote(
                    ticker=ticker, price=price,
                    change=round(change, 2), change_pct=round(pct, 2),
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("yfinance quote failed for %s: %s", ticker, e)
                return Quote(ticker=ticker, price=0, timestamp=time.time())


# ── Tradier Provider ─────────────────────────────────────────────────────────

class TradierProvider(DataProvider):
    """Real-time data via Tradier API v1."""

    def __init__(self, api_key: str, sandbox: bool = True):
        self._api_key = api_key
        self._base = (
            "https://sandbox.tradier.com/v1" if sandbox
            else "https://api.tradier.com/v1"
        )
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "tradier"

    def _request(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._api_key}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_expirations(self, ticker: str) -> list[str]:
        with self._lock:
            try:
                data = self._request("/markets/options/expirations", {"symbol": ticker})
                exps = data.get("expirations", {}).get("date", [])
                if isinstance(exps, str):
                    exps = [exps]
                return exps[:12]
            except Exception as e:
                log.warning("Tradier expirations failed for %s: %s", ticker, e)
                return []

    def get_options_chain(self, ticker: str, expiry: str) -> OptionsChainResult:
        with self._lock:
            time.sleep(0.2)  # rate limit
            try:
                data = self._request("/markets/options/chains", {
                    "symbol": ticker,
                    "expiration": expiry,
                    "greeks": "false",
                })
                options = data.get("options", {}).get("option", [])
                if isinstance(options, dict):
                    options = [options]

                calls, puts = [], []
                for opt in options:
                    row = OptionRow(
                        strike=float(opt.get("strike", 0)),
                        last=float(opt.get("last", 0) or 0),
                        bid=float(opt.get("bid", 0) or 0),
                        ask=float(opt.get("ask", 0) or 0),
                        volume=int(opt.get("volume", 0) or 0),
                        open_interest=int(opt.get("open_interest", 0) or 0),
                        option_type=opt.get("option_type", "call"),
                    )
                    if opt.get("option_type") == "put":
                        puts.append(row)
                    else:
                        calls.append(row)

                return OptionsChainResult(
                    ticker=ticker, expiry=expiry,
                    calls=calls, puts=puts,
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("Tradier chain failed for %s/%s: %s", ticker, expiry, e)
                return OptionsChainResult(ticker=ticker, expiry=expiry, timestamp=time.time())

    def get_quote(self, ticker: str) -> Quote:
        with self._lock:
            try:
                data = self._request("/markets/quotes", {"symbols": ticker})
                q = data.get("quotes", {}).get("quote", {})
                return Quote(
                    ticker=ticker,
                    price=float(q.get("last", 0) or 0),
                    change=float(q.get("change", 0) or 0),
                    change_pct=float(q.get("change_percentage", 0) or 0),
                    volume=int(q.get("volume", 0) or 0),
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("Tradier quote failed for %s: %s", ticker, e)
                return Quote(ticker=ticker, price=0, timestamp=time.time())


# ── Robinhood Legacy Provider (Full: Stocks + Options + Crypto) ──────────────

class RobinhoodProvider(DataProvider):
    """Full Robinhood access via robin_stocks (username/password).

    Capabilities: stocks, options (puts/calls/spreads), AND crypto.
    This is the ONLY path that supports options trading on Robinhood.
    """

    MODE = "legacy"
    CAPABILITIES = ["stocks", "options", "crypto"]

    def __init__(self, username: str = "", password: str = ""):
        self._username = username
        self._password = password
        self._logged_in = False
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "robinhood"

    def _ensure_login(self):
        if self._logged_in:
            return
        if not self._username or not self._password:
            raise RuntimeError("Robinhood credentials not configured (need FORGE_ROBINHOOD_USER + FORGE_ROBINHOOD_PASS)")
        require_provider_dependencies("robinhood")
        import robin_stocks.robinhood as r
        r.login(self._username, self._password)
        self._logged_in = True

    # ── Options (full support via robin_stocks) ──

    def get_expirations(self, ticker: str) -> list[str]:
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                chains = r.options.get_chains(ticker)
                if not chains or "expiration_dates" not in chains:
                    return []
                return chains["expiration_dates"][:12]
            except Exception as e:
                log.warning("Robinhood expirations failed for %s: %s", ticker, e)
                return []

    def get_options_chain(self, ticker: str, expiry: str) -> OptionsChainResult:
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r

                calls_data = r.options.find_options_by_expiration(
                    [ticker], expirationDate=expiry, optionType="call"
                ) or []
                puts_data = r.options.find_options_by_expiration(
                    [ticker], expirationDate=expiry, optionType="put"
                ) or []

                calls = []
                for opt in calls_data:
                    calls.append(OptionRow(
                        strike=float(opt.get("strike_price", 0) or 0),
                        last=float(opt.get("last_trade_price", 0) or 0),
                        bid=float(opt.get("bid_price", 0) or 0),
                        ask=float(opt.get("ask_price", 0) or 0),
                        volume=int(opt.get("volume", 0) or 0),
                        open_interest=int(opt.get("open_interest", 0) or 0),
                        option_type="call",
                    ))

                puts = []
                for opt in puts_data:
                    puts.append(OptionRow(
                        strike=float(opt.get("strike_price", 0) or 0),
                        last=float(opt.get("last_trade_price", 0) or 0),
                        bid=float(opt.get("bid_price", 0) or 0),
                        ask=float(opt.get("ask_price", 0) or 0),
                        volume=int(opt.get("volume", 0) or 0),
                        open_interest=int(opt.get("open_interest", 0) or 0),
                        option_type="put",
                    ))

                return OptionsChainResult(
                    ticker=ticker, expiry=expiry,
                    calls=calls, puts=puts,
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("Robinhood chain failed for %s/%s: %s", ticker, expiry, e)
                return OptionsChainResult(ticker=ticker, expiry=expiry, timestamp=time.time())

    # ── Stock quotes ──

    def get_quote(self, ticker: str) -> Quote:
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                # Try stock quote first, fall back to crypto
                info = r.stocks.get_latest_price(ticker, includeExtendedHours=True)
                if info and info[0]:
                    price = float(info[0])
                    fundamentals = r.stocks.get_fundamentals(ticker)
                    prev_close = float(fundamentals[0].get("open", price) or price) if fundamentals else price
                    change = price - prev_close
                    pct = (change / prev_close * 100) if prev_close else 0
                    volume_data = r.stocks.get_quotes(ticker)
                    vol = int(volume_data[0].get("volume", 0) or 0) if volume_data else 0
                    return Quote(
                        ticker=ticker, price=price,
                        change=round(change, 2), change_pct=round(pct, 2),
                        volume=vol, timestamp=time.time(),
                    )
                # Fallback: crypto
                crypto_info = r.crypto.get_crypto_quote(ticker)
                price = float(crypto_info.get("mark_price", 0) or 0)
                return Quote(
                    ticker=ticker, price=price,
                    volume=int(float(crypto_info.get("volume", 0) or 0)),
                    timestamp=time.time(),
                )
            except Exception as e:
                log.warning("Robinhood quote failed for %s: %s", ticker, e)
                return Quote(ticker=ticker, price=0, timestamp=time.time())

    # ── Stock trading ──

    def order_stock(self, ticker: str, side: str, quantity: float,
                    order_type: str = "market", price: float | None = None) -> dict:
        """Place a stock order. side: 'buy' | 'sell'."""
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                if side == "buy":
                    if order_type == "limit" and price:
                        result = r.orders.order_buy_limit(ticker, int(quantity), price)
                    else:
                        result = r.orders.order_buy_market(ticker, int(quantity))
                else:
                    if order_type == "limit" and price:
                        result = r.orders.order_sell_limit(ticker, int(quantity), price)
                    else:
                        result = r.orders.order_sell_market(ticker, int(quantity))
                return {
                    "status": "submitted",
                    "order_id": result.get("id", ""),
                    "side": side, "ticker": ticker,
                    "quantity": quantity, "asset_type": "stock",
                }
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}

    # ── Options trading ──

    def order_option(self, ticker: str, expiry: str, strike: float,
                     option_type: str, side: str, quantity: int,
                     order_type: str = "market", price: float | None = None) -> dict:
        """Place an options order.

        option_type: 'call' | 'put'
        side: 'buy' | 'sell'
        """
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                if side == "buy":
                    result = r.orders.order_buy_option_limit(
                        "debit", price or 0.01, ticker, quantity,
                        expiry, strike, option_type,
                    )
                else:
                    result = r.orders.order_sell_option_limit(
                        "credit", price or 0.01, ticker, quantity,
                        expiry, strike, option_type,
                    )
                return {
                    "status": "submitted",
                    "order_id": result.get("id", ""),
                    "side": side, "ticker": ticker,
                    "strike": strike, "expiry": expiry,
                    "option_type": option_type,
                    "quantity": quantity, "asset_type": "option",
                }
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}

    # ── Crypto ──

    def get_crypto_positions(self) -> list[dict]:
        """Get current crypto positions."""
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                positions = r.crypto.get_crypto_positions()
                return [
                    {
                        "ticker": p.get("currency", {}).get("code", ""),
                        "quantity": float(p.get("quantity", 0) or 0),
                        "avg_price": float(p.get("cost_bases", [{}])[0].get("direct_cost_basis", 0) or 0)
                        / max(float(p.get("quantity", 1) or 1), 0.0001),
                    }
                    for p in positions
                    if float(p.get("quantity", 0) or 0) > 0
                ]
            except Exception as e:
                log.warning("Robinhood positions failed: %s", e)
                return []

    def order_crypto(self, symbol: str, side: str, quantity: float) -> dict:
        """Place a crypto order. side: 'buy' | 'sell'."""
        with self._lock:
            try:
                self._ensure_login()
                import robin_stocks.robinhood as r
                if side == "buy":
                    result = r.orders.order_buy_crypto_by_quantity(symbol, quantity)
                else:
                    result = r.orders.order_sell_crypto_by_quantity(symbol, quantity)
                return {
                    "status": "submitted",
                    "order_id": result.get("id", ""),
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "asset_type": "crypto",
                }
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}


# ── Robinhood Crypto API Provider (API Key — Crypto Only) ────────────────────

class RobinhoodCryptoAPIProvider(DataProvider):
    """Crypto-only access via Robinhood Crypto API (API key + secret).

    NO stocks. NO options. Crypto trading only.
    Cleaner auth (API key vs storing login credentials).
    """

    MODE = "api-key"
    CAPABILITIES = ["crypto"]

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self._api_key = api_key
        self._api_secret = api_secret
        self._lock = threading.Lock()
        self._base = "https://trading.robinhood.com/api/v1"

    @property
    def name(self) -> str:
        return "robinhood-crypto"

    def _make_headers(self, method: str, path: str, body: str = "") -> dict:
        """Build Ed25519-signed headers for Robinhood Crypto API."""
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        timestamp = str(int(time.time()))
        message = f"{self._api_key}{timestamp}{path}{method}{body}"

        # Decode base64 private key → Ed25519 signing key (first 32 bytes)
        private_bytes = base64.b64decode(self._api_secret)
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes[:32])
        signature = base64.b64encode(
            private_key.sign(message.encode("utf-8"))
        ).decode("utf-8")

        return {
            "x-api-key": self._api_key,
            "x-signature": signature,
            "x-timestamp": timestamp,
            "Content-Type": "application/json; charset=utf-8",
        }

    def _request(self, method: str, path: str, body: str = "") -> dict:
        if not self._api_key or not self._api_secret:
            raise RuntimeError("Robinhood Crypto API key not configured (need FORGE_ROBINHOOD_API_KEY + FORGE_ROBINHOOD_API_SECRET)")
        require_provider_dependencies("robinhood-crypto")
        url = f"{self._base}{path}"
        headers = self._make_headers(method, path, body)
        req = urllib.request.Request(url, method=method, headers=headers)
        if body:
            req.data = body.encode("utf-8")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_expirations(self, ticker: str) -> list[str]:
        return []  # Crypto has no options

    def get_options_chain(self, ticker: str, expiry: str) -> OptionsChainResult:
        return OptionsChainResult(ticker=ticker, expiry=expiry, timestamp=time.time())

    def get_trading_pairs(self, *symbols: str) -> list[dict]:
        """Get trading pair info for one or more symbols (e.g. 'BTC-USD')."""
        params = "&".join(f"symbol={s}" for s in symbols)
        path = f"/crypto/trading/trading_pairs/?{params}" if params else "/crypto/trading/trading_pairs/"
        data = self._request("GET", path)
        return data.get("results", []) if isinstance(data, dict) else data

    def get_quote(self, ticker: str) -> Quote:
        with self._lock:
            try:
                symbol = f"{ticker}-USD" if not ticker.endswith("-USD") else ticker
                path = f"/crypto/marketdata/best_bid_ask/?symbol={symbol}"
                data = self._request("GET", path)
                # Response: {"results": [{"symbol": "BTC-USD", "bid_inclusive_of_sell_spread": "...", "ask_inclusive_of_buy_spread": "...", ...}]}
                results = data.get("results", []) if isinstance(data, dict) else []
                if results:
                    r = results[0]
                    bid = float(r.get("bid_inclusive_of_sell_spread", 0) or r.get("price", 0) or 0)
                    ask = float(r.get("ask_inclusive_of_buy_spread", 0) or 0)
                    price = (bid + ask) / 2 if (bid and ask) else bid or ask
                    return Quote(
                        ticker=ticker, price=round(price, 4),
                        timestamp=time.time(),
                    )
                # Fallback: estimated price endpoint
                path2 = f"/crypto/marketdata/estimated_price/?symbol={symbol}&side=bid&quantity=1"
                data2 = self._request("GET", path2)
                ep = float(data2.get("estimated_price", 0) or 0)
                return Quote(ticker=ticker, price=round(ep, 4), timestamp=time.time())
            except Exception as e:
                log.warning("Robinhood Crypto API quote failed for %s: %s", ticker, e)
                return Quote(ticker=ticker, price=0, timestamp=time.time())

    def get_account(self) -> dict:
        """Get crypto account info."""
        return self._request("GET", "/crypto/trading/accounts/")

    def get_holdings(self, *asset_codes: str) -> list[dict]:
        """Get crypto holdings, optionally filtered by asset code (e.g. 'BTC')."""
        params = "&".join(f"asset_code={c}" for c in asset_codes)
        path = f"/crypto/trading/holdings/?{params}" if params else "/crypto/trading/holdings/"
        data = self._request("GET", path)
        return data.get("results", []) if isinstance(data, dict) else data

    def order_crypto(self, symbol: str, side: str, quantity: float,
                     order_type: str = "market", price: float | None = None) -> dict:
        """Place a crypto order via Robinhood Crypto API."""
        import uuid
        with self._lock:
            try:
                sym = f"{symbol}-USD" if not symbol.endswith("-USD") else symbol
                payload = {
                    "client_order_id": str(uuid.uuid4()),
                    "side": side,
                    "symbol": sym,
                    "type": order_type,
                }
                if order_type == "market":
                    payload["market_order_config"] = {
                        "asset_quantity": str(quantity),
                    }
                elif order_type == "limit" and price:
                    payload["limit_order_config"] = {
                        "asset_quantity": str(quantity),
                        "limit_price": str(price),
                        "time_in_force": "gtc",
                    }
                elif order_type == "stop" and price:
                    payload["stop_loss_order_config"] = {
                        "asset_quantity": str(quantity),
                        "stop_price": str(price),
                        "time_in_force": "gtc",
                    }
                elif order_type == "stop_limit" and price:
                    payload["stop_limit_order_config"] = {
                        "asset_quantity": str(quantity),
                        "limit_price": str(price),
                        "stop_price": str(price),
                        "time_in_force": "gtc",
                    }

                body = json.dumps(payload)
                result = self._request("POST", "/crypto/trading/orders/", body)
                return {
                    "status": result.get("state", "submitted"),
                    "order_id": result.get("id", ""),
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "asset_type": "crypto",
                    "message": f"Crypto {side} {quantity} {symbol} — {result.get('state', 'submitted')}",
                }
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending crypto order."""
        try:
            self._request("POST", f"/crypto/trading/orders/{order_id}/cancel/")
            return True
        except Exception:
            return False

    def get_orders(self) -> list[dict]:
        """Get crypto order history."""
        try:
            data = self._request("GET", "/crypto/trading/orders/")
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception:
            return []


# ── Provider Factory ─────────────────────────────────────────────────────────

_providers: dict[str, DataProvider] = {}
_providers_lock = threading.Lock()


def get_provider(name: str = "yfinance", **kwargs) -> DataProvider:
    """Get or create a singleton provider by name.

    Supported names:
      yfinance         — free delayed data (no config needed)
      tradier          — real-time via API key
      robinhood        — FULL access: stocks + options + crypto (user/pass)
      robinhood-crypto — crypto-only via Robinhood Crypto API key

    Providers that require credentials are NOT cached when instantiated
    with blank credentials, so a later call with real credentials can
    replace the unconfigured instance.
    """
    with _providers_lock:
        if name in _providers:
            return _providers[name]

        if name == "yfinance":
            p = YFinanceProvider()
        elif name == "tradier":
            p = TradierProvider(
                api_key=kwargs.get("api_key", ""),
                sandbox=kwargs.get("sandbox", True),
            )
        elif name == "robinhood":
            p = RobinhoodProvider(
                username=kwargs.get("username", ""),
                password=kwargs.get("password", ""),
            )
        elif name == "robinhood-crypto":
            p = RobinhoodCryptoAPIProvider(
                api_key=kwargs.get("api_key", ""),
                api_secret=kwargs.get("api_secret", ""),
            )
        else:
            raise ValueError(f"Unknown provider: {name}")

        # Don't cache providers created with blank credentials
        should_cache = True
        if name == "tradier" and not kwargs.get("api_key"):
            should_cache = False
        elif name == "robinhood" and not (kwargs.get("username") and kwargs.get("password")):
            should_cache = False
        elif name == "robinhood-crypto" and not (kwargs.get("api_key") and kwargs.get("api_secret")):
            should_cache = False

        if should_cache:
            _providers[name] = p
        return p


def get_provider_from_config(name: str = "") -> DataProvider:
    """Return a provider hydrated from the active trading config."""
    from forge.config import (
        TRADING_DEFAULT_PROVIDER,
        TRADING_ROBINHOOD_API_KEY,
        TRADING_ROBINHOOD_API_SECRET,
        TRADING_ROBINHOOD_PASS,
        TRADING_ROBINHOOD_USER,
        TRADING_TRADIER_API_KEY,
        TRADING_TRADIER_SANDBOX,
    )

    resolved = name or TRADING_DEFAULT_PROVIDER
    if resolved == "tradier":
        return get_provider(
            "tradier",
            api_key=TRADING_TRADIER_API_KEY,
            sandbox=TRADING_TRADIER_SANDBOX,
        )
    if resolved == "robinhood":
        return get_provider(
            "robinhood",
            username=TRADING_ROBINHOOD_USER,
            password=TRADING_ROBINHOOD_PASS,
        )
    if resolved == "robinhood-crypto":
        return get_provider(
            "robinhood-crypto",
            api_key=TRADING_ROBINHOOD_API_KEY,
            api_secret=TRADING_ROBINHOOD_API_SECRET,
        )
    return get_provider("yfinance")
