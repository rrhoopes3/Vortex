"""
Trading module — AI Trading Assistant.

Combines PCRBOT PCR analysis with Forge agent tools for
real-time options sentiment, trade execution, and portfolio tracking.
"""
from forge.trading.engine import TradingEngine
from forge.trading.providers import (
    YFinanceProvider, TradierProvider,
    RobinhoodProvider, RobinhoodCryptoAPIProvider,
)

__all__ = [
    "TradingEngine",
    "YFinanceProvider", "TradierProvider",
    "RobinhoodProvider", "RobinhoodCryptoAPIProvider",
]


def check_trading_readiness() -> dict:
    """Check trading subsystem readiness with full credential validation.

    Returns dict with:
      - state: "ready" | "degraded" | "unavailable"
      - provider: active provider name
      - broker: active broker type
      - issues: list of problem descriptions
    """
    from forge.config import (
        TRADING_ENABLED, TRADING_DEFAULT_PROVIDER, TRADING_PAPER_MODE,
        TRADING_TRADIER_API_KEY, TRADING_TRADIER_ACCOUNT_ID,
        TRADING_ROBINHOOD_USER, TRADING_ROBINHOOD_PASS,
        TRADING_ROBINHOOD_API_KEY, TRADING_ROBINHOOD_API_SECRET,
    )

    issues = []
    state = "ready"

    if not TRADING_ENABLED:
        return {"state": "unavailable", "provider": "", "broker": "",
                "issues": ["FORGE_TRADING_ENABLED is false"]}

    # Provider readiness
    provider = TRADING_DEFAULT_PROVIDER
    if provider == "tradier":
        if not TRADING_TRADIER_API_KEY:
            issues.append("FORGE_TRADIER_API_KEY missing — cannot use Tradier provider")
            state = "unavailable"
    elif provider == "robinhood":
        if not TRADING_ROBINHOOD_USER or not TRADING_ROBINHOOD_PASS:
            issues.append("Robinhood credentials incomplete — need FORGE_ROBINHOOD_USER + FORGE_ROBINHOOD_PASS for full access (stocks/options/crypto)")
            state = "unavailable"
    elif provider == "robinhood-crypto":
        if not TRADING_ROBINHOOD_API_KEY or not TRADING_ROBINHOOD_API_SECRET:
            issues.append("Robinhood Crypto API incomplete — need FORGE_ROBINHOOD_API_KEY + FORGE_ROBINHOOD_API_SECRET")
            state = "unavailable"

    # Broker readiness
    broker = "paper"
    if not TRADING_PAPER_MODE:
        if provider == "robinhood" and TRADING_ROBINHOOD_USER:
            broker = "robinhood"
        elif provider == "robinhood-crypto" and TRADING_ROBINHOOD_API_KEY:
            broker = "robinhood-crypto"
        elif TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID:
            broker = "tradier"
        elif TRADING_TRADIER_API_KEY and not TRADING_TRADIER_ACCOUNT_ID:
            issues.append("FORGE_TRADIER_ACCOUNT_ID missing — live trading unavailable, using paper mode")
            broker = "paper"
            if state == "ready":
                state = "degraded"
        else:
            issues.append("No broker credentials — falling back to paper trading")
            broker = "paper"
            if state == "ready":
                state = "degraded"

    return {
        "state": state,
        "provider": provider,
        "broker": broker,
        "issues": issues,
    }
