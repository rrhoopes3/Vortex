"""
Tests for the escalation tool — graceful human handoff.

Validates:
  - EscalationError is raised correctly
  - Escalation tool is registered and available
  - Tool is in CORE_TOOLS (always available)
  - Escalation categories are validated
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.tools.escalation import EscalationError, _escalate
from forge.tools.registry import CORE_TOOLS, TOOL_CATEGORIES, ToolRegistry


class TestEscalationError:
    def test_basic_escalation(self):
        with pytest.raises(EscalationError) as exc_info:
            _escalate(reason="Need clarification", category="ambiguity")
        assert exc_info.value.reason == "Need clarification"
        assert exc_info.value.category == "ambiguity"
        assert exc_info.value.context == ""

    def test_escalation_with_context(self):
        with pytest.raises(EscalationError) as exc_info:
            _escalate(
                reason="Destructive operation",
                category="risk",
                context="About to delete /var/log/*",
            )
        assert exc_info.value.category == "risk"
        assert "delete" in exc_info.value.context

    def test_escalation_error_message(self):
        with pytest.raises(EscalationError) as exc_info:
            _escalate(reason="Cannot resolve", category="error")
        assert "[error]" in str(exc_info.value).lower()

    def test_escalation_all_categories(self):
        for cat in ["ambiguity", "risk", "error", "expertise"]:
            with pytest.raises(EscalationError) as exc_info:
                _escalate(reason=f"Test {cat}", category=cat)
            assert exc_info.value.category == cat


class TestEscalationRegistration:
    def test_in_core_tools(self):
        assert "escalate_to_human" in CORE_TOOLS

    def test_in_tool_categories(self):
        assert "escalation" in TOOL_CATEGORIES
        assert "escalate_to_human" in TOOL_CATEGORIES["escalation"]

    def test_registered_in_registry(self):
        from forge.tools import create_registry
        reg = create_registry()
        assert "escalate_to_human" in reg.list_tools()

    def test_tool_definition_exists(self):
        from forge.tools import create_registry
        reg = create_registry()
        raw = reg.get_raw_tools()
        names = [t["name"] for t in raw]
        assert "escalate_to_human" in names

    def test_tool_schema(self):
        from forge.tools import create_registry
        reg = create_registry()
        raw = reg.get_raw_tools(only={"escalate_to_human"})
        assert len(raw) == 1
        tool = raw[0]
        assert "reason" in tool["parameters"]["properties"]
        assert "category" in tool["parameters"]["properties"]
        assert "context" in tool["parameters"]["properties"]
        assert "reason" in tool["parameters"]["required"]
        assert "category" in tool["parameters"]["required"]


class TestEscalationExecution:
    def test_execute_raises(self):
        from forge.tools import create_registry
        reg = create_registry()
        with pytest.raises(EscalationError):
            reg.execute("escalate_to_human", {
                "reason": "Test escalation",
                "category": "ambiguity",
            })

    def test_execute_with_context(self):
        from forge.tools import create_registry
        reg = create_registry()
        with pytest.raises(EscalationError) as exc_info:
            reg.execute("escalate_to_human", {
                "reason": "Need approval for refactor",
                "category": "risk",
                "context": "Files: main.py, config.py",
            })
        assert exc_info.value.reason == "Need approval for refactor"
        assert exc_info.value.context == "Files: main.py, config.py"
