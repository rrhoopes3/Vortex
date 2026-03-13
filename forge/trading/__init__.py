"""Trading module readiness and public exports."""

from forge.trading.engine import TradingEngine
from forge.trading.providers import (
    RobinhoodCryptoAPIProvider,
    RobinhoodProvider,
    TradierProvider,
    YFinanceProvider,
)
from forge.trading_deps import get_provider_dependency_status

__all__ = [
    "TradingEngine",
    "YFinanceProvider",
    "TradierProvider",
    "RobinhoodProvider",
    "RobinhoodCryptoAPIProvider",
]


def check_trading_readiness() -> dict:
    """Check trading readiness, including optional Robinhood dependencies."""
    from forge.config import (
        TRADING_DEFAULT_PROVIDER,
        TRADING_ENABLED,
        TRADING_PAPER_MODE,
        TRADING_ROBINHOOD_API_KEY,
        TRADING_ROBINHOOD_API_SECRET,
        TRADING_ROBINHOOD_PASS,
        TRADING_ROBINHOOD_USER,
        TRADING_TRADIER_ACCOUNT_ID,
        TRADING_TRADIER_API_KEY,
    )

    issues = []
    state = "ready"

    if not TRADING_ENABLED:
        return {
            "state": "unavailable",
            "provider": "",
            "broker": "",
            "issues": ["FORGE_TRADING_ENABLED is false"],
        }

    provider = TRADING_DEFAULT_PROVIDER
    if provider == "tradier":
        if not TRADING_TRADIER_API_KEY:
            issues.append("FORGE_TRADIER_API_KEY missing; cannot use Tradier provider")
            state = "unavailable"
    elif provider == "robinhood":
        if not TRADING_ROBINHOOD_USER or not TRADING_ROBINHOOD_PASS:
            issues.append(
                "Robinhood credentials incomplete; need FORGE_ROBINHOOD_USER and FORGE_ROBINHOOD_PASS"
            )
            state = "unavailable"
        dep_status = get_provider_dependency_status("robinhood")
        if not dep_status["available"]:
            issues.append(dep_status["issue"])
            state = "unavailable"
    elif provider == "robinhood-crypto":
        if not TRADING_ROBINHOOD_API_KEY or not TRADING_ROBINHOOD_API_SECRET:
            issues.append(
                "Robinhood Crypto API incomplete; need FORGE_ROBINHOOD_API_KEY and "
                "FORGE_ROBINHOOD_API_SECRET"
            )
            state = "unavailable"
        dep_status = get_provider_dependency_status("robinhood-crypto")
        if not dep_status["available"]:
            issues.append(dep_status["issue"])
            state = "unavailable"

    broker = "paper"
    if not TRADING_PAPER_MODE:
        if (
            provider == "robinhood"
            and TRADING_ROBINHOOD_USER
            and TRADING_ROBINHOOD_PASS
        ):
            broker = "robinhood"
        elif (
            provider == "robinhood-crypto"
            and TRADING_ROBINHOOD_API_KEY
            and TRADING_ROBINHOOD_API_SECRET
        ):
            broker = "robinhood-crypto"
        elif TRADING_TRADIER_API_KEY and TRADING_TRADIER_ACCOUNT_ID:
            broker = "tradier"
        elif TRADING_TRADIER_API_KEY and not TRADING_TRADIER_ACCOUNT_ID:
            issues.append("FORGE_TRADIER_ACCOUNT_ID missing; live trading unavailable, using paper")
            broker = "paper"
            if state == "ready":
                state = "degraded"
        else:
            issues.append("No live broker credentials available; falling back to paper trading")
            broker = "paper"
            if state == "ready":
                state = "degraded"

    return {
        "state": state,
        "provider": provider,
        "broker": broker,
        "issues": issues,
    }
