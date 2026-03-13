"""
Trading module — AI Trading Assistant.

Combines PCRBOT PCR analysis with Forge agent tools for
real-time options sentiment, trade execution, and portfolio tracking.
"""
from forge.trading.engine import TradingEngine
from forge.trading.providers import YFinanceProvider, TradierProvider, RobinhoodProvider

__all__ = ["TradingEngine", "YFinanceProvider", "TradierProvider", "RobinhoodProvider"]
