"""
Tests for hindsight directive generation — OpenClaw-RL (arXiv:2603.10165).

Covers: generate_directive, detect_reassignment_directives.
"""
import pytest

from forge.directives import generate_directive, detect_reassignment_directives
from forge.models import PlanStep, StepResult
from forge.vault import NotesEntry


# ── generate_directive ────────────────────────────────────────────────────

class TestGenerateDirective:
    def test_basic_directive(self):
        failed = StepResult(
            step_number=1, status="failed",
            delegatee_model="gpt-4o", tools_used=["run_command"],
            error="Command timed out",
        )
        success = StepResult(
            step_number=1, status="success",
            delegatee_model="grok-4-1-fast-reasoning",
            tools_used=["read_file", "write_file"],
            output="Fixed the config file",
        )
        step = PlanStep(step_number=1, title="Fix config", description="Fix the configuration file")

        directive = generate_directive(failed, success, step, "fix config issue")
        assert isinstance(directive, NotesEntry)
        assert directive.pattern_type == "directive"
        assert "AVOID" in directive.content
        assert "PREFER" in directive.content
        assert "gpt-4o" in directive.content
        assert "grok-4-1-fast-reasoning" in directive.content

    def test_directive_domain_detection(self):
        failed = StepResult(step_number=1, status="failed", delegatee_model="model_a")
        success = StepResult(step_number=1, status="success", delegatee_model="model_b",
                             output="wrote tests")
        step = PlanStep(step_number=1, title="Run pytest", description="Run python tests")

        directive = generate_directive(failed, success, step, "run python tests")
        assert directive.domain in ("python", "testing")

    def test_directive_content_truncation(self):
        failed = StepResult(
            step_number=1, status="failed",
            delegatee_model="model_a",
            error="x" * 500,
        )
        success = StepResult(
            step_number=1, status="success",
            delegatee_model="model_b",
            output="y" * 500,
        )
        step = PlanStep(step_number=1, title="T", description="D")

        directive = generate_directive(failed, success, step, "task")
        assert len(directive.content) <= 300

    def test_directive_no_error(self):
        failed = StepResult(step_number=1, status="failed", delegatee_model="m1")
        success = StepResult(step_number=1, status="success", delegatee_model="m2",
                             output="ok")
        step = PlanStep(step_number=1, title="Step", description="Do thing")

        directive = generate_directive(failed, success, step, "task")
        assert "AVOID" in directive.content
        assert "PREFER" in directive.content

    def test_directive_no_tools(self):
        failed = StepResult(step_number=1, status="failed", delegatee_model="m1")
        success = StepResult(step_number=1, status="success", delegatee_model="m2")
        step = PlanStep(step_number=1, title="Step", description="Think")

        directive = generate_directive(failed, success, step, "task")
        assert "no tools" in directive.content


# ── detect_reassignment_directives ────────────────────────────────────────

class TestDetectReassignmentDirectives:
    def test_no_reassignments(self):
        results = [
            StepResult(step_number=1, status="success", was_reassigned=False),
            StepResult(step_number=2, status="success", was_reassigned=False),
        ]
        steps = [
            PlanStep(step_number=1, title="A", description="Do A"),
            PlanStep(step_number=2, title="B", description="Do B"),
        ]
        directives = detect_reassignment_directives(results, steps, "task")
        assert directives == []

    def test_one_reassignment_success(self):
        results = [
            StepResult(
                step_number=1, status="success",
                was_reassigned=True, reassigned_from="gpt-4o",
                delegatee_model="grok-4-1-fast-reasoning",
                tools_used=["read_file"],
                output="Fixed it",
            ),
        ]
        steps = [PlanStep(step_number=1, title="Fix bug", description="Fix the bug")]

        directives = detect_reassignment_directives(results, steps, "fix the bug")
        assert len(directives) == 1
        assert directives[0].pattern_type == "directive"
        assert "gpt-4o" in directives[0].content

    def test_reassignment_failure_ignored(self):
        """If a step was reassigned but still failed, no directive is generated."""
        results = [
            StepResult(
                step_number=1, status="failed",
                was_reassigned=True, reassigned_from="gpt-4o",
                delegatee_model="grok-4-1-fast-reasoning",
                error="Still failed",
            ),
        ]
        steps = [PlanStep(step_number=1, title="Fix", description="Fix it")]

        directives = detect_reassignment_directives(results, steps, "fix it")
        assert directives == []

    def test_multiple_reassignments(self):
        results = [
            StepResult(step_number=1, status="success", was_reassigned=True,
                       reassigned_from="m1", delegatee_model="m2", output="ok"),
            StepResult(step_number=2, status="success", was_reassigned=False),
            StepResult(step_number=3, status="success", was_reassigned=True,
                       reassigned_from="m3", delegatee_model="m4", output="done"),
        ]
        steps = [
            PlanStep(step_number=1, title="S1", description="D1"),
            PlanStep(step_number=2, title="S2", description="D2"),
            PlanStep(step_number=3, title="S3", description="D3"),
        ]

        directives = detect_reassignment_directives(results, steps, "multi task")
        assert len(directives) == 2

    def test_missing_step_skipped(self):
        """If results reference a step_number not in steps list, skip it."""
        results = [
            StepResult(step_number=99, status="success", was_reassigned=True,
                       reassigned_from="m1", delegatee_model="m2", output="ok"),
        ]
        steps = [PlanStep(step_number=1, title="S1", description="D1")]

        directives = detect_reassignment_directives(results, steps, "task")
        assert directives == []
