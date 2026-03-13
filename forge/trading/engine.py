"""
Core trading engine — PCR calculation, alerts, history, and session management.

Ported from PCRBOT with enhancements for agent integration.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue

from forge.trading.providers import (
    DataProvider, OptionsChainResult, Quote, get_provider,
)

log = logging.getLogger("forge.trading.engine")

# ── Preset Tickers (from PCRBOT) ────────────────────────────────────────────

PRESET_TICKERS = {
    "indices": ["^SPX", "^NDX", "^RUT", "OEX", "XSP"],
    "volatility": ["^VIX"],
    "etfs": ["SPY", "QQQ", "IWM", "DIA"],
    "sectors": ["XLE", "XLF", "XLK", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"],
}

ALL_PRESET_TICKERS = []
for _group in PRESET_TICKERS.values():
    ALL_PRESET_TICKERS.extend(_group)


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class PCRResult:
    ticker: str
    expiry: str
    vol_ratio: float | None
    oi_ratio: float | None
    put_vol: int
    call_vol: int
    put_oi: int
    call_oi: int
    sentiment: str  # "bullish" | "bearish" | "neutral"
    timestamp: float

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "expiry": self.expiry,
            "vol_ratio": self.vol_ratio,
            "oi_ratio": self.oi_ratio,
            "put_vol": self.put_vol,
            "call_vol": self.call_vol,
            "put_oi": self.put_oi,
            "call_oi": self.call_oi,
            "sentiment": self.sentiment,
            "timestamp": self.timestamp,
        }


@dataclass
class Alert:
    alert_id: str
    ticker: str
    metric: str  # "vol_ratio" | "oi_ratio"
    threshold: float
    direction: str  # "above" | "below"
    triggered: bool = False
    last_value: float | None = None

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "ticker": self.ticker,
            "metric": self.metric,
            "threshold": self.threshold,
            "direction": self.direction,
            "triggered": self.triggered,
            "last_value": self.last_value,
        }


# ── Sentiment Classification ────────────────────────────────────────────────

def classify_sentiment(vol_ratio: float | None, oi_ratio: float | None) -> str:
    """Classify market sentiment from PCR ratios.

    >1.2 → bearish (more puts than calls)
    <0.7 → bullish (more calls than puts)
    else → neutral
    """
    ratio = vol_ratio if vol_ratio is not None else oi_ratio
    if ratio is None:
        return "neutral"
    if ratio > 1.2:
        return "bearish"
    if ratio < 0.7:
        return "bullish"
    return "neutral"


# ── PCR Calculation ──────────────────────────────────────────────────────────

def calculate_pcr(chain: OptionsChainResult) -> PCRResult:
    """Calculate Put/Call ratios from an options chain."""
    put_vol = sum(p.volume for p in chain.puts)
    call_vol = sum(c.volume for c in chain.calls)
    put_oi = sum(p.open_interest for p in chain.puts)
    call_oi = sum(c.open_interest for c in chain.calls)

    vol_ratio = round(put_vol / call_vol, 4) if call_vol > 0 else None
    oi_ratio = round(put_oi / call_oi, 4) if call_oi > 0 else None

    return PCRResult(
        ticker=chain.ticker,
        expiry=chain.expiry,
        vol_ratio=vol_ratio,
        oi_ratio=oi_ratio,
        put_vol=put_vol,
        call_vol=call_vol,
        put_oi=put_oi,
        call_oi=call_oi,
        sentiment=classify_sentiment(vol_ratio, oi_ratio),
        timestamp=chain.timestamp or time.time(),
    )


# ── Trading Engine (Singleton) ──────────────────────────────────────────────

class TradingEngine:
    """Central trading engine managing data fetching, PCR calculation, alerts, and history."""

    def __init__(self, data_dir: Path | None = None):
        self._lock = threading.RLock()
        self._data_dir = data_dir or Path(__file__).parent.parent / "data" / "trading"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._alerts: dict[str, Alert] = {}
        self._history: dict[str, list[dict]] = {}  # key: "ticker_expiry" → list of PCR dicts
        self._subscribers: list[Queue] = []

        # Alert checker thread
        self._alert_stop = threading.Event()
        self._alert_thread: threading.Thread | None = None

        self._load_history()

    # ── Provider Access ──────────────────────────────────────────────────

    def _get_provider(self, provider_name: str = "") -> DataProvider:
        from forge.config import (
            TRADING_DEFAULT_PROVIDER, TRADING_TRADIER_API_KEY,
            TRADING_TRADIER_SANDBOX, TRADING_ROBINHOOD_USER, TRADING_ROBINHOOD_PASS,
        )
        name = provider_name or TRADING_DEFAULT_PROVIDER
        if name == "tradier":
            return get_provider("tradier", api_key=TRADING_TRADIER_API_KEY,
                                sandbox=TRADING_TRADIER_SANDBOX)
        if name == "robinhood":
            return get_provider("robinhood", username=TRADING_ROBINHOOD_USER,
                                password=TRADING_ROBINHOOD_PASS)
        return get_provider("yfinance")

    # ── PCR Data ─────────────────────────────────────────────────────────

    def get_expirations(self, ticker: str, provider: str = "") -> list[str]:
        return self._get_provider(provider).get_expirations(ticker)

    def get_pcr(self, ticker: str, expiry: str = "", provider: str = "") -> PCRResult:
        """Fetch PCR for a ticker. If no expiry given, uses nearest available."""
        prov = self._get_provider(provider)

        if not expiry:
            exps = prov.get_expirations(ticker)
            if not exps:
                return PCRResult(
                    ticker=ticker, expiry="", vol_ratio=None, oi_ratio=None,
                    put_vol=0, call_vol=0, put_oi=0, call_oi=0,
                    sentiment="neutral", timestamp=time.time(),
                )
            expiry = exps[0]

        chain = prov.get_options_chain(ticker, expiry)
        result = calculate_pcr(chain)

        # Store in history
        self._record_history(result)

        # Notify subscribers
        self._notify({"type": "pcr_update", "data": result.to_dict()})

        return result

    def get_quote(self, ticker: str, provider: str = "") -> Quote:
        return self._get_provider(provider).get_quote(ticker)

    def get_options_chain(self, ticker: str, expiry: str = "",
                          provider: str = "", min_volume: int = 0) -> OptionsChainResult:
        """Get raw options chain, optionally filtered by minimum volume."""
        prov = self._get_provider(provider)
        if not expiry:
            exps = prov.get_expirations(ticker)
            expiry = exps[0] if exps else ""
        if not expiry:
            return OptionsChainResult(ticker=ticker, expiry="", timestamp=time.time())

        chain = prov.get_options_chain(ticker, expiry)
        if min_volume > 0:
            chain.calls = [c for c in chain.calls if c.volume >= min_volume]
            chain.puts = [p for p in chain.puts if p.volume >= min_volume]
        return chain

    # ── Multi-Ticker Analysis ────────────────────────────────────────────

    def analyze_sentiment(self, tickers: list[str], provider: str = "") -> dict:
        """Analyze PCR sentiment across multiple tickers."""
        results = {}
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for ticker in tickers:
            pcr = self.get_pcr(ticker, provider=provider)
            results[ticker] = pcr.to_dict()
            if pcr.sentiment == "bullish":
                bullish_count += 1
            elif pcr.sentiment == "bearish":
                bearish_count += 1
            else:
                neutral_count += 1

        total = len(tickers)
        if bullish_count > total / 2:
            market_sentiment = "bullish"
        elif bearish_count > total / 2:
            market_sentiment = "bearish"
        else:
            market_sentiment = "mixed"

        return {
            "tickers": results,
            "summary": {
                "market_sentiment": market_sentiment,
                "bullish": bullish_count,
                "bearish": bearish_count,
                "neutral": neutral_count,
                "total": total,
            },
            "timestamp": time.time(),
        }

    # ── Alerts ───────────────────────────────────────────────────────────

    def set_alert(self, ticker: str, metric: str, threshold: float,
                  direction: str) -> Alert:
        alert_id = str(uuid.uuid4())[:8]
        alert = Alert(
            alert_id=alert_id,
            ticker=ticker,
            metric=metric,
            threshold=threshold,
            direction=direction,
        )
        with self._lock:
            self._alerts[alert_id] = alert
        self._ensure_alert_thread()
        return alert

    def remove_alert(self, alert_id: str) -> bool:
        with self._lock:
            return self._alerts.pop(alert_id, None) is not None

    def get_alerts(self) -> list[Alert]:
        with self._lock:
            return list(self._alerts.values())

    def _ensure_alert_thread(self):
        if self._alert_thread and self._alert_thread.is_alive():
            return
        self._alert_stop.clear()
        self._alert_thread = threading.Thread(target=self._alert_loop, daemon=True)
        self._alert_thread.start()

    def _alert_loop(self):
        """Background thread checking alerts every 30 seconds."""
        while not self._alert_stop.is_set():
            with self._lock:
                alerts = list(self._alerts.values())

            for alert in alerts:
                try:
                    pcr = self.get_pcr(alert.ticker)
                    value = pcr.vol_ratio if alert.metric == "vol_ratio" else pcr.oi_ratio
                    if value is None:
                        continue
                    alert.last_value = value
                    triggered = (
                        (alert.direction == "above" and value > alert.threshold) or
                        (alert.direction == "below" and value < alert.threshold)
                    )
                    if triggered and not alert.triggered:
                        alert.triggered = True
                        self._notify({
                            "type": "alert_triggered",
                            "data": {
                                **alert.to_dict(),
                                "current_value": value,
                            },
                        })
                    elif not triggered:
                        alert.triggered = False
                except Exception as e:
                    log.warning("Alert check failed for %s: %s", alert.ticker, e)

            self._alert_stop.wait(30)

    def stop(self):
        self._alert_stop.set()

    # ── SSE Subscribers ──────────────────────────────────────────────────

    def subscribe(self) -> Queue:
        q: Queue = Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue):
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _notify(self, msg: dict):
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass

    # ── History ──────────────────────────────────────────────────────────

    def _history_key(self, ticker: str, expiry: str) -> str:
        return f"{ticker}_{expiry}"

    def _record_history(self, pcr: PCRResult):
        key = self._history_key(pcr.ticker, pcr.expiry)
        with self._lock:
            if key not in self._history:
                self._history[key] = []
            self._history[key].append(pcr.to_dict())
            # Rolling 100 records
            if len(self._history[key]) > 100:
                self._history[key] = self._history[key][-100:]

    def get_history(self, ticker: str, expiry: str = "") -> list[dict]:
        with self._lock:
            if expiry:
                key = self._history_key(ticker, expiry)
                return list(self._history.get(key, []))
            # Return all expiries for this ticker
            result = []
            for key, records in self._history.items():
                if key.startswith(f"{ticker}_"):
                    result.extend(records)
            result.sort(key=lambda r: r.get("timestamp", 0))
            return result[-100:]

    def _load_history(self):
        history_file = self._data_dir / "history.json"
        if history_file.exists():
            try:
                with open(history_file) as f:
                    self._history = json.load(f)
            except Exception as e:
                log.warning("Failed to load trading history: %s", e)

    def save_history(self):
        history_file = self._data_dir / "history.json"
        with self._lock:
            try:
                with open(history_file, "w") as f:
                    json.dump(self._history, f, indent=2)
            except Exception as e:
                log.warning("Failed to save trading history: %s", e)

    # ── Preset Tickers ───────────────────────────────────────────────────

    def get_preset_tickers(self) -> dict:
        return dict(PRESET_TICKERS)

    def get_all_tickers(self) -> list[str]:
        return list(ALL_PRESET_TICKERS)


# ── Singleton ────────────────────────────────────────────────────────────────

_engine: TradingEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> TradingEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            from forge.config import TRADING_DATA_DIR
            _engine = TradingEngine(data_dir=TRADING_DATA_DIR)
        return _engine
