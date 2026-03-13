"""
Toll relay middleware — wraps generators, meters messages, yields toll events.

Usage in Orchestrator:
    gen = planner.plan(client, task)
    gen = toll_relay.meter(gen, sender="orchestrator", receiver="planner", session_id=task_id)
    # Now iterate gen as usual — original messages + toll events interleaved
"""
from __future__ import annotations

import logging
from typing import Any, Generator

from forge.toll.ledger import Ledger
from forge.toll.models import TollMessage
from forge.toll.rates import RateEngine

log = logging.getLogger("forge.toll.relay")

# Map SSE message types → toll message types
_MSG_TYPE_MAP = {
    "status": "status_update",
    "plan_content": "plan_content",
    "step_start": "step_execution",
    "content": "llm_response",
    "tool_call": "tool_invocation",
    "tool_result": "tool_result",
    "token_usage": "token_usage",
}


class TollRelay:
    """Toll relay that wraps generator pipelines and meters inter-agent messages.

    For each metered message:
    1. Calculate toll via RateEngine
    2. Deduct from sender wallet via Ledger
    3. Yield the original message (unchanged)
    4. Yield a toll_deducted event
    5. At end, yield a toll_summary event
    """

    def __init__(self, ledger: Ledger, rate_engine: RateEngine, enabled: bool = True):
        self.ledger = ledger
        self.rate_engine = rate_engine
        self.enabled = enabled
        self._session_counters: dict[str, int] = {}

    def meter(
        self,
        generator: Generator,
        sender: str,
        receiver: str,
        session_id: str = "",
        message_type: str = "",
    ) -> Generator[dict, None, Any]:
        """Wrap a generator, metering each yielded message.

        Yields original messages unchanged, plus toll_deducted events
        after each metered message, and a toll_summary at the end.
        """
        if not self.enabled:
            return (yield from generator)

        # Ensure wallets exist
        self.ledger.get_or_create_wallet(sender)
        self.ledger.get_or_create_wallet(receiver)

        hop_counter = 0
        session_key = session_id or "unknown"

        try:
            result = None
            while True:
                try:
                    msg = next(generator)
                except StopIteration as e:
                    result = e.value
                    break

                # Classify the message
                msg_type = message_type or _MSG_TYPE_MAP.get(msg.get("type", ""), "other")
                rate = self.rate_engine.get_rate(msg_type)

                token_count = _estimate_tokens(msg) if rate else 0
                toll_amount = self.rate_engine.calculate(
                    rate, token_count, self._session_counters.get(session_key, 0),
                ) if rate else 0.0

                if toll_amount > 0:
                    hop_counter += 1
                    self._session_counters[session_key] = (
                        self._session_counters.get(session_key, 0) + 1
                    )
                    creator_cut = round(toll_amount * (rate.creator_rake_pct / 100.0), 8)

                    toll_msg = TollMessage(
                        sender=sender,
                        receiver=receiver,
                        message_type=msg_type,
                        payload_summary=str(msg.get("content", ""))[:200],
                        token_count=token_count,
                        toll_amount_usd=toll_amount,
                        creator_revenue_usd=creator_cut,
                        session_id=session_id,
                        hop_number=hop_counter,
                    )

                    receipt = self.ledger.process_toll(toll_msg)

                    # Yield original message first (unchanged)
                    yield msg

                    # Yield toll event
                    yield {
                        "type": "toll_deducted",
                        "message_id": toll_msg.message_id,
                        "sender": sender,
                        "receiver": receiver,
                        "message_type": msg_type,
                        "toll_usd": toll_msg.toll_amount_usd,
                        "creator_revenue_usd": toll_msg.creator_revenue_usd,
                        "payer_balance": receipt.payer_balance_after,
                        "session_id": session_id,
                    }
                else:
                    # Not metered — pass through unchanged
                    yield msg

            # Yield session toll summary at end
            if hop_counter > 0:
                summary = self.ledger.get_session_summary(session_id)
                yield {
                    "type": "toll_summary",
                    "session_id": session_id,
                    "total_messages": summary.total_messages_metered,
                    "total_tolls_usd": summary.total_tolls_usd,
                    "total_creator_revenue_usd": summary.total_creator_revenue_usd,
                    "messages_by_type": summary.messages_by_type,
                }

            return result

        except Exception:
            raise  # don't swallow errors from the inner generator


def _estimate_tokens(msg: dict) -> int:
    """Rough token estimate: ~4 chars per token."""
    content = str(msg.get("content", ""))
    return max(1, len(content) // 4)
