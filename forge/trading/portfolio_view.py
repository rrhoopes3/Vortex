"""
Helpers for building a portfolio snapshot for UI and agent consumers.

For live Robinhood crypto trading we want the portfolio view to reflect the
brokerage account state, not only locally recorded fills.
"""
from __future__ import annotations

import logging

from forge.trading.portfolio import Position, get_portfolio_manager

log = logging.getLogger("forge.trading.portfolio_view")


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _holding_ticker(holding: dict) -> str:
    return (
        str(holding.get("ticker", "") or "").upper()
        or str(holding.get("asset_code", "") or "").upper()
        or str((holding.get("currency") or {}).get("code", "") or "").upper()
        or str(holding.get("symbol", "") or "").replace("-USD", "").upper()
    )


def _holding_quantity(holding: dict) -> float:
    for key in ("quantity", "total_quantity", "quantity_available_for_trading"):
        quantity = _to_float(holding.get(key))
        if quantity > 0:
            return quantity
    return 0.0


def _holding_avg_price(holding: dict, quantity: float) -> float:
    for key in ("avg_price", "average_price", "average_buy_price", "cost_basis_price"):
        avg = _to_float(holding.get(key))
        if avg > 0:
            return avg

    cost_bases = holding.get("cost_bases") or []
    if isinstance(cost_bases, dict):
        cost_bases = [cost_bases]

    for basis in cost_bases:
        for key in ("average_price", "average_buy_price", "cost_basis_price"):
            avg = _to_float(basis.get(key))
            if avg > 0:
                return avg

        direct_cost = _to_float(basis.get("direct_cost_basis"))
        basis_qty = (
            _to_float(basis.get("direct_quantity"))
            or _to_float(basis.get("quantity"))
            or quantity
        )
        if direct_cost > 0 and basis_qty > 0:
            return direct_cost / basis_qty

    total_cost = _to_float(holding.get("cost_basis")) or _to_float(holding.get("total_cost_basis"))
    if total_cost > 0 and quantity > 0:
        return total_cost / quantity

    return 0.0


def _positions_from_holdings(holdings: list[dict]) -> list[Position]:
    positions: list[Position] = []
    for holding in holdings:
        ticker = _holding_ticker(holding)
        quantity = _holding_quantity(holding)
        if not ticker or quantity <= 0:
            continue
        positions.append(
            Position(
                ticker=ticker,
                quantity=quantity,
                avg_price=_holding_avg_price(holding, quantity),
                side="long",
            )
        )
    return positions


def _live_positions(provider_name: str = "") -> tuple[bool, list[Position], str]:
    """Return live positions when the active provider can expose them directly."""
    from forge.config import TRADING_DEFAULT_PROVIDER, TRADING_PAPER_MODE
    from forge.trading.providers import get_provider_from_config

    if TRADING_PAPER_MODE:
        return False, [], provider_name or TRADING_DEFAULT_PROVIDER

    effective_provider = provider_name or TRADING_DEFAULT_PROVIDER
    if effective_provider not in {"robinhood", "robinhood-crypto"}:
        return False, [], effective_provider

    try:
        provider = get_provider_from_config(provider_name)
        if effective_provider == "robinhood-crypto" and hasattr(provider, "get_holdings"):
            holdings = provider.get_holdings() or []
            return True, _positions_from_holdings(holdings), effective_provider
        if effective_provider == "robinhood" and hasattr(provider, "get_crypto_positions"):
            holdings = provider.get_crypto_positions() or []
            return True, _positions_from_holdings(holdings), effective_provider
    except Exception as exc:
        log.warning("Live portfolio fetch failed for %s: %s", effective_provider, exc)

    return False, [], effective_provider


def build_portfolio_summary(provider_name: str = "", price_fetcher=None) -> dict:
    """Build a portfolio summary, preferring live brokerage holdings when available."""
    pm = get_portfolio_manager()
    fetched_live, positions, effective_provider = _live_positions(provider_name)

    if not fetched_live:
        if price_fetcher is None and provider_name:
            try:
                from forge.trading.engine import get_engine

                engine = get_engine()
                price_fetcher = lambda ticker: engine.get_quote(ticker, provider=provider_name).price
            except Exception:
                price_fetcher = None

        summary = pm.get_summary(price_fetcher=price_fetcher)
        summary["source"] = "local"
        return summary

    if price_fetcher is None:
        try:
            from forge.trading.engine import get_engine

            engine = get_engine()
            price_fetcher = lambda ticker: engine.get_quote(ticker, provider=effective_provider).price
        except Exception:
            price_fetcher = None

    if price_fetcher:
        for pos in positions:
            try:
                quote = price_fetcher(pos.ticker)
                if quote and quote > 0:
                    pos.current_price = quote
            except Exception:
                pass

    realized = pm.get_realized_pnl()
    unrealized = sum(pos.unrealized_pnl for pos in positions)
    return {
        "positions": [pos.to_dict() for pos in positions],
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(realized + unrealized, 2),
        "position_count": len(positions),
        "source": "brokerage",
    }
