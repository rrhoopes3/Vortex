"""
Portfolio manager — tracks positions, orders, and P&L.

SQLite-backed, thread-safe, following forge/toll/ledger.py patterns.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

log = logging.getLogger("forge.trading.portfolio")


@dataclass
class Position:
    ticker: str
    quantity: float
    avg_price: float
    current_price: float = 0.0
    side: str = "long"  # "long" | "short"

    @property
    def unrealized_pnl(self) -> float:
        if self.side == "long":
            return (self.current_price - self.avg_price) * self.quantity
        return (self.avg_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        cost = self.avg_price * self.quantity
        if cost == 0:
            return 0
        return self.unrealized_pnl / cost * 100

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "avg_price": round(self.avg_price, 4),
            "current_price": round(self.current_price, 4),
            "side": self.side,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "market_value": round(self.current_price * self.quantity, 2),
        }


class PortfolioManager:
    """Thread-safe portfolio tracker backed by SQLite."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    quantity REAL NOT NULL DEFAULT 0,
                    avg_price REAL NOT NULL DEFAULT 0,
                    side TEXT NOT NULL DEFAULT 'long',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    order_type TEXT NOT NULL DEFAULT 'market',
                    price REAL,
                    fill_price REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    broker TEXT NOT NULL DEFAULT 'paper',
                    created_at REAL NOT NULL,
                    filled_at REAL
                );
                CREATE TABLE IF NOT EXISTS realized_pnl (
                    id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pnl REAL NOT NULL,
                    closed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    ticker TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    price REAL,
                    decision TEXT NOT NULL,
                    full_text TEXT,
                    tool_calls TEXT,
                    position_qty REAL,
                    position_value REAL,
                    cycle INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_orders_ticker ON orders(ticker);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
                CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
                CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp);
            """)

    # ── Positions ────────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM positions WHERE quantity > 0").fetchall()
            return [
                Position(
                    ticker=r["ticker"],
                    quantity=r["quantity"],
                    avg_price=r["avg_price"],
                    side=r["side"],
                )
                for r in rows
            ]

    def update_position(self, ticker: str, quantity: float, price: float,
                        side: str = "buy") -> Position:
        """Update position after a fill. Handles averaging and closing."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM positions WHERE ticker = ?", (ticker,)
            ).fetchone()

            now = time.time()
            if row is None:
                # New position
                self._conn.execute(
                    "INSERT INTO positions (ticker, quantity, avg_price, side, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (ticker, quantity, price, "long" if side == "buy" else "short", now),
                )
            else:
                existing_qty = row["quantity"]
                existing_avg = row["avg_price"]

                if side == "buy" and row["side"] == "long":
                    # Add to long position — average up/down
                    new_qty = existing_qty + quantity
                    new_avg = (existing_avg * existing_qty + price * quantity) / new_qty
                    self._conn.execute(
                        "UPDATE positions SET quantity = ?, avg_price = ?, updated_at = ? WHERE ticker = ?",
                        (new_qty, new_avg, now, ticker),
                    )
                elif side == "sell" and row["side"] == "long":
                    # Close/reduce long position
                    close_qty = min(quantity, existing_qty)
                    pnl = (price - existing_avg) * close_qty
                    self._conn.execute(
                        "INSERT INTO realized_pnl (id, ticker, quantity, entry_price, exit_price, pnl, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (str(uuid.uuid4())[:8], ticker, close_qty, existing_avg, price, pnl, now),
                    )
                    remaining = existing_qty - close_qty
                    if remaining <= 0:
                        self._conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
                    else:
                        self._conn.execute(
                            "UPDATE positions SET quantity = ?, updated_at = ? WHERE ticker = ?",
                            (remaining, now, ticker),
                        )
                else:
                    # Simple update for other cases
                    new_qty = existing_qty + quantity
                    new_avg = (existing_avg * existing_qty + price * quantity) / max(new_qty, 0.0001)
                    self._conn.execute(
                        "UPDATE positions SET quantity = ?, avg_price = ?, updated_at = ? WHERE ticker = ?",
                        (new_qty, new_avg, now, ticker),
                    )

            self._conn.commit()
            return self._get_position(ticker)

    def _get_position(self, ticker: str) -> Position:
        row = self._conn.execute(
            "SELECT * FROM positions WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not row:
            return Position(ticker=ticker, quantity=0, avg_price=0)
        return Position(
            ticker=row["ticker"],
            quantity=row["quantity"],
            avg_price=row["avg_price"],
            side=row["side"],
        )

    # ── Orders ───────────────────────────────────────────────────────────

    def record_order(self, ticker: str, side: str, quantity: float,
                     order_id: str | None = None,
                     order_type: str = "market", price: float | None = None,
                     fill_price: float | None = None, status: str = "filled",
                     broker: str = "paper") -> dict:
        order_id = order_id or str(uuid.uuid4())[:8]
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO orders
                   (order_id, ticker, side, quantity, order_type, price, fill_price, status, broker, created_at, filled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, ticker, side, quantity, order_type, price,
                 fill_price, status, broker, now, now if status == "filled" else None),
            )
            self._conn.commit()
        return {
            "order_id": order_id, "ticker": ticker, "side": side,
            "quantity": quantity, "order_type": order_type,
            "fill_price": fill_price, "status": status, "broker": broker,
        }

    def get_orders(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── P&L ──────────────────────────────────────────────────────────────

    def get_realized_pnl(self) -> float:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(SUM(pnl), 0) as total FROM realized_pnl").fetchone()
            return float(row["total"])

    def get_summary(self, price_fetcher=None) -> dict:
        """Get portfolio summary with live mark-to-market pricing.

        price_fetcher: callable(ticker) -> float. If None, falls back to
        the trading engine's quote provider. Positions without a live price
        keep current_price=0 (clearly wrong, but won't silently lie).
        """
        positions = self.get_positions()

        # Mark-to-market: fetch live prices for every open position
        if price_fetcher is None:
            try:
                from forge.trading.engine import get_engine
                engine = get_engine()
                price_fetcher = lambda t: engine.get_quote(t).price
            except Exception:
                price_fetcher = None

        if price_fetcher:
            for pos in positions:
                try:
                    quote = price_fetcher(pos.ticker)
                    if quote and quote > 0:
                        pos.current_price = quote
                    else:
                        log.warning("Mark-to-market: %s returned price=%s, treating as unavailable",
                                    pos.ticker, quote)
                except Exception:
                    pass  # leave at 0 — caller sees the gap

        realized = self.get_realized_pnl()
        unrealized = sum(p.unrealized_pnl for p in positions)
        return {
            "positions": [p.to_dict() for p in positions],
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(realized + unrealized, 2),
            "position_count": len(positions),
        }

    # ── Decisions ──────────────────────────────────────────────────────

    def log_decision(self, *, ticker: str, strategy: str, model: str,
                     price: float | None, decision: str, full_text: str = "",
                     tool_calls: list | None = None,
                     position_qty: float = 0, position_value: float = 0,
                     cycle: int = 0):
        """Persist an agent decision for later analysis."""
        import json as _json
        with self._lock:
            self._conn.execute(
                """INSERT INTO decisions
                   (timestamp, ticker, strategy, model, price, decision,
                    full_text, tool_calls, position_qty, position_value, cycle)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), ticker, strategy, model, price, decision,
                 full_text, _json.dumps(tool_calls or []),
                 position_qty, position_value, cycle),
            )
            self._conn.commit()

    def get_decisions(self, ticker: str | None = None, limit: int = 100) -> list[dict]:
        """Retrieve logged decisions, newest first."""
        with self._lock:
            if ticker:
                rows = self._conn.execute(
                    "SELECT * FROM decisions WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Daily Recap ──────────────────────────────────────────────────

    def get_daily_recap(self, date_str: str | None = None) -> dict:
        """Build a trading recap for a single calendar day.

        Parameters
        ----------
        date_str : str, optional
            ISO date like ``"2026-03-14"``.  Defaults to today (UTC).

        Returns
        -------
        dict with keys: date, orders, realized_trades, decisions, stats
        """
        import datetime as _dt

        if date_str:
            day = _dt.date.fromisoformat(date_str)
        else:
            day = _dt.datetime.utcnow().date()

        day_start = _dt.datetime.combine(day, _dt.time.min).timestamp()
        day_end = _dt.datetime.combine(day + _dt.timedelta(days=1), _dt.time.min).timestamp()

        with self._lock:
            # Orders placed during the day
            orders = [
                dict(r) for r in self._conn.execute(
                    "SELECT * FROM orders WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
                    (day_start, day_end),
                ).fetchall()
            ]

            # Realized P&L entries closed during the day
            realized = [
                dict(r) for r in self._conn.execute(
                    "SELECT * FROM realized_pnl WHERE closed_at >= ? AND closed_at < ? ORDER BY closed_at",
                    (day_start, day_end),
                ).fetchall()
            ]

            # Agent decisions during the day
            decisions = [
                dict(r) for r in self._conn.execute(
                    "SELECT * FROM decisions WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
                    (day_start, day_end),
                ).fetchall()
            ]

        # ── Compute stats ──
        buy_orders = [o for o in orders if o.get("side") == "buy"]
        sell_orders = [o for o in orders if o.get("side") == "sell"]

        buy_volume = sum(
            (o.get("fill_price") or o.get("price") or 0) * o.get("quantity", 0)
            for o in buy_orders
        )
        sell_volume = sum(
            (o.get("fill_price") or o.get("price") or 0) * o.get("quantity", 0)
            for o in sell_orders
        )

        wins = [r for r in realized if r.get("pnl", 0) > 0]
        losses = [r for r in realized if r.get("pnl", 0) < 0]
        flat = [r for r in realized if r.get("pnl", 0) == 0]
        total_realized = sum(r.get("pnl", 0) for r in realized)

        best_trade = max(realized, key=lambda r: r.get("pnl", 0)) if realized else None
        worst_trade = min(realized, key=lambda r: r.get("pnl", 0)) if realized else None

        # Tickers the agents looked at
        decision_actions = {}
        for d in decisions:
            action = d.get("decision", "HOLD").upper().split()[0]
            decision_actions[action] = decision_actions.get(action, 0) + 1

        stats = {
            "total_orders": len(orders),
            "buy_orders": len(buy_orders),
            "sell_orders": len(sell_orders),
            "buy_volume_usd": round(buy_volume, 2),
            "sell_volume_usd": round(sell_volume, 2),
            "trades_closed": len(realized),
            "wins": len(wins),
            "losses": len(losses),
            "flat": len(flat),
            "win_rate": round(len(wins) / len(realized) * 100, 1) if realized else None,
            "realized_pnl": round(total_realized, 2),
            "best_trade": {
                "ticker": best_trade["ticker"],
                "pnl": round(best_trade["pnl"], 2),
            } if best_trade else None,
            "worst_trade": {
                "ticker": worst_trade["ticker"],
                "pnl": round(worst_trade["pnl"], 2),
            } if worst_trade else None,
            "agent_decisions": len(decisions),
            "agent_actions": decision_actions,
        }

        return {
            "date": day.isoformat(),
            "orders": orders,
            "realized_trades": realized,
            "decisions": decisions,
            "stats": stats,
        }

    def reset(self):
        with self._lock:
            self._conn.executescript("""
                DELETE FROM positions;
                DELETE FROM orders;
                DELETE FROM realized_pnl;
            """)


# ── Singleton ────────────────────────────────────────────────────────────────

_pm: PortfolioManager | None = None
_pm_lock = threading.Lock()


def get_portfolio_manager() -> PortfolioManager:
    global _pm
    with _pm_lock:
        if _pm is None:
            from forge.config import TRADING_DATA_DIR
            _pm = PortfolioManager(str(TRADING_DATA_DIR / "portfolio.db"))
        return _pm
