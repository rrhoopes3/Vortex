"""
Rate engine — configurable toll pricing per message type.
"""
from __future__ import annotations

from forge.toll.models import TollRate


# Default toll rates: the "highway price list"
_DEFAULT_RATES: dict[str, TollRate] = {
    "plan_request": TollRate(message_type="plan_request", base_rate_usd=0.001),
    "plan_content": TollRate(message_type="plan_content", base_rate_usd=0.0005, per_token_rate=0.000001),
    "step_execution": TollRate(message_type="step_execution", base_rate_usd=0.002),
    "llm_response": TollRate(message_type="llm_response", base_rate_usd=0.0005, per_token_rate=0.000002),
    "tool_invocation": TollRate(message_type="tool_invocation", base_rate_usd=0.001),
    "tool_result": TollRate(message_type="tool_result", base_rate_usd=0.0003),
    "status_update": TollRate(message_type="status_update", base_rate_usd=0.0),
    "token_usage": TollRate(message_type="token_usage", base_rate_usd=0.0),
    "other": TollRate(message_type="other", base_rate_usd=0.0001),
}


class RateEngine:
    """Calculates toll amounts based on configurable rates."""

    def __init__(self, custom_rates: dict[str, TollRate] | None = None):
        self.rates: dict[str, TollRate] = dict(_DEFAULT_RATES)
        if custom_rates:
            self.rates.update(custom_rates)

    def get_rate(self, message_type: str) -> TollRate | None:
        """Look up the toll rate for a message type (falls back to 'other')."""
        return self.rates.get(message_type, self.rates.get("other"))

    def calculate(self, rate: TollRate, token_count: int = 0,
                  session_message_count: int = 0) -> float:
        """Calculate toll amount, optionally applying volume discount."""
        base = rate.base_rate_usd + (token_count * rate.per_token_rate)
        if (rate.volume_discount_threshold > 0
                and session_message_count >= rate.volume_discount_threshold):
            base *= (1.0 - rate.volume_discount_pct / 100.0)
        return round(base, 8)

    def set_rate(self, message_type: str, rate: TollRate) -> None:
        self.rates[message_type] = rate

    def all_rates(self) -> dict[str, dict]:
        """Return all rates as plain dicts (for API serialization)."""
        return {k: v.model_dump() for k, v in self.rates.items()}
