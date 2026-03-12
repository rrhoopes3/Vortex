"""
Escalation Tool — enables agents to gracefully hand off to humans.

Inspired by OpenAI's agent guide: agents should be equipped to escalate tasks
to humans when encountering errors, uncertainty, or high-risk decisions.

The escalation tool pauses execution and emits a structured escalation event
that the orchestrator/UI can surface to the user.
"""
from __future__ import annotations
import json
import logging

from forge.tools.registry import ToolRegistry

log = logging.getLogger("forge.tools.escalation")


class EscalationError(Exception):
    """Raised when the agent escalates to a human. Caught by the executor loop."""

    def __init__(self, reason: str, category: str, context: str = ""):
        self.reason = reason
        self.category = category
        self.context = context
        super().__init__(f"[{category}] {reason}")


def _escalate(reason: str, category: str = "general", context: str = "") -> str:
    """Escalate the current task to a human operator.

    This tool should be called when the agent encounters:
    - Ambiguous requirements that need human clarification
    - High-risk operations that require human approval
    - Errors that cannot be resolved autonomously
    - Decisions that require domain expertise beyond the agent's capability

    Args:
        reason: Clear explanation of why escalation is needed
        category: Type of escalation (ambiguity, risk, error, expertise)
        context: Additional context about the current state

    Returns:
        Acknowledgment message (execution will pause after this)
    """
    log.info("Agent escalation triggered: [%s] %s", category, reason)
    raise EscalationError(reason=reason, category=category, context=context)


def register(reg: ToolRegistry):
    """Register the escalation tool."""
    reg.register(
        name="escalate_to_human",
        description=(
            "Escalate the current task to a human operator. Use this when you encounter: "
            "(1) ambiguous requirements needing clarification, "
            "(2) high-risk operations needing approval (e.g. destructive changes, large refactors), "
            "(3) errors you cannot resolve after multiple attempts, or "
            "(4) decisions requiring domain expertise you lack. "
            "Provide a clear reason and category. Execution will pause until a human responds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Clear explanation of why escalation is needed and what decision/input is required from the human",
                },
                "category": {
                    "type": "string",
                    "enum": ["ambiguity", "risk", "error", "expertise"],
                    "description": "Type of escalation: ambiguity (unclear requirements), risk (dangerous operation), error (unresolvable failure), expertise (needs domain knowledge)",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context: what was attempted, current state, relevant file paths, etc.",
                },
            },
            "required": ["reason", "category"],
        },
        handler=_escalate,
    )
