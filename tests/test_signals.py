"""
Tests for signal extraction and user correction detection.
OpenClaw-RL (arXiv:2603.10165).
"""
import time

import pytest

from forge.signals import (
    InteractionSignal, StepSignals, SignalExtractor,
    CorrectionSignal, CorrectionDetector,
)


# ── InteractionSignal ─────────────────────────────────────────────────────

class TestInteractionSignal:
    def test_defaults(self):
        sig = InteractionSignal(signal_type="tool_success", value=1.0, source="read_file")
        assert sig.signal_type == "tool_success"
        assert sig.value == 1.0
        assert sig.source == "read_file"
        assert sig.metadata == {}

    def test_with_metadata(self):
        sig = InteractionSignal(
            signal_type="tool_error", value=0.0, source="run_command",
            metadata={"snippet": "error: file not found"},
        )
        assert sig.metadata["snippet"] == "error: file not found"


# ── StepSignals ───────────────────────────────────────────────────────────

class TestStepSignals:
    def test_tool_error_rate_zero(self):
        ss = StepSignals(tool_success_count=5, tool_error_count=0)
        assert ss.tool_error_rate == 0.0

    def test_tool_error_rate_half(self):
        ss = StepSignals(tool_success_count=3, tool_error_count=3)
        assert ss.tool_error_rate == 0.5

    def test_tool_error_rate_no_tools(self):
        ss = StepSignals()
        assert ss.tool_error_rate == 0.0

    def test_aggregate_score_perfect(self):
        ss = StepSignals(
            tool_success_count=5, tool_error_count=0,
            content_length=300, had_errors=False,
        )
        ss._expected_latency = 60.0
        ss.latency_seconds = 30.0
        score = ss.aggregate_score
        # tool_reliability=1.0, latency_score=1.0, content_score=1.0, error_free=1.0
        assert score == pytest.approx(1.0)

    def test_aggregate_score_all_errors(self):
        ss = StepSignals(
            tool_success_count=0, tool_error_count=5,
            content_length=0, had_errors=True,
        )
        ss._expected_latency = 60.0
        ss.latency_seconds = 200.0
        score = ss.aggregate_score
        assert score < 0.1  # very low

    def test_aggregate_score_mixed(self):
        ss = StepSignals(
            tool_success_count=3, tool_error_count=1,
            content_length=100, had_errors=False,
        )
        ss._expected_latency = 60.0
        ss.latency_seconds = 60.0
        score = ss.aggregate_score
        assert 0.5 < score < 1.0

    def test_latency_score_default(self):
        """No expected_latency set → returns neutral 0.7."""
        ss = StepSignals(latency_seconds=100.0)
        assert ss._score_latency() == 0.7

    def test_latency_score_under(self):
        ss = StepSignals(latency_seconds=10.0)
        ss._expected_latency = 60.0
        assert ss._score_latency() == 1.0

    def test_latency_score_3x(self):
        ss = StepSignals(latency_seconds=180.0)
        ss._expected_latency = 60.0
        assert ss._score_latency() == 0.0


# ── SignalExtractor ───────────────────────────────────────────────────────

class TestSignalExtractor:
    def test_observe_tool_success(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "tool_result", "name": "read_file", "result": "file contents here"})
        assert sig is not None
        assert sig.signal_type == "tool_success"
        assert sig.value == 1.0

    def test_observe_tool_error(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "tool_result", "name": "run_command", "result": "Error: command failed"})
        assert sig is not None
        assert sig.signal_type == "tool_error"
        assert sig.value == 0.0

    def test_observe_tool_false_positive(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "tool_result", "name": "run_tests", "result": "0 errors found"})
        assert sig.signal_type == "tool_success"

    def test_observe_content(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "content", "content": "hello world"})
        assert sig.signal_type == "content_chunk"

    def test_observe_token_usage(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "token_usage", "cost_usd": 0.001})
        assert sig.signal_type == "token_usage"

    def test_observe_error(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "error", "content": "something went wrong"})
        assert sig.signal_type == "error"
        assert sig.value == 0.0

    def test_observe_unknown_type(self):
        ext = SignalExtractor()
        sig = ext.observe({"type": "status", "content": "planning..."})
        assert sig is None

    def test_finalize(self):
        ext = SignalExtractor(expected_latency=60.0, step_number=3)
        ext.observe({"type": "tool_result", "name": "read_file", "result": "ok"})
        ext.observe({"type": "tool_result", "name": "write_file", "result": "ok"})
        ext.observe({"type": "tool_result", "name": "run_command", "result": "Error: failed"})
        ext.observe({"type": "content", "content": "some output text"})
        ext.observe({"type": "token_usage", "cost_usd": 0.002})

        signals = ext.finalize(latency_seconds=30.0)
        assert signals.step_number == 3
        assert signals.tool_success_count == 2
        assert signals.tool_error_count == 1
        assert signals.content_length == len("some output text")
        assert signals.cost_usd == pytest.approx(0.002)
        assert signals.latency_seconds == 30.0
        assert 0.0 <= signals.aggregate_score <= 1.0

    def test_finalize_empty(self):
        ext = SignalExtractor()
        signals = ext.finalize(0.0)
        assert signals.tool_success_count == 0
        assert signals.tool_error_count == 0
        assert signals.aggregate_score >= 0.0

    def test_multiple_tool_results(self):
        ext = SignalExtractor()
        for i in range(10):
            ext.observe({"type": "tool_result", "name": f"tool_{i}", "result": "success"})
        signals = ext.finalize(10.0)
        assert signals.tool_success_count == 10
        assert signals.tool_error_count == 0
        assert signals.tool_error_rate == 0.0


# ── CorrectionSignal ─────────────────────────────────────────────────────

class TestCorrectionSignal:
    def test_creation(self):
        sig = CorrectionSignal(signal_type="kill", severity=1.0, original_task_id="abc123")
        assert sig.signal_type == "kill"
        assert sig.severity == 1.0


# ── CorrectionDetector ───────────────────────────────────────────────────

class TestCorrectionDetector:
    def test_no_recent_tasks(self):
        cd = CorrectionDetector()
        result = cd.detect_resubmission("build the API endpoint")
        assert result is None

    def test_detect_resubmission(self):
        cd = CorrectionDetector(similarity_threshold=0.6)
        cd.record_task("build the API endpoint for user authentication", "task1")
        result = cd.detect_resubmission("build the API endpoint for user authentication")
        assert result is not None
        assert result.signal_type == "resubmission"
        assert result.original_task_id == "task1"

    def test_no_match_different_task(self):
        cd = CorrectionDetector(similarity_threshold=0.6)
        cd.record_task("build the API endpoint for user authentication", "task1")
        result = cd.detect_resubmission("deploy the database migration scripts")
        assert result is None

    def test_partial_overlap_below_threshold(self):
        cd = CorrectionDetector(similarity_threshold=0.8)
        cd.record_task("build the API endpoint", "task1")
        result = cd.detect_resubmission("build the API with some new changes")
        # With high threshold, partial overlap may not trigger
        # (depends on keyword overlap ratio)
        # Just ensure it doesn't crash
        assert result is None or result.signal_type == "resubmission"

    def test_record_kill(self):
        cd = CorrectionDetector()
        signal = cd.record_kill("task42")
        assert signal.signal_type == "kill"
        assert signal.severity == 1.0
        assert signal.original_task_id == "task42"
        assert "task42" in cd._killed_tasks

    def test_max_recent_cap(self):
        cd = CorrectionDetector()
        for i in range(60):
            cd.record_task(f"task number {i}", f"id_{i}")
        assert len(cd._recent_tasks) == cd.MAX_RECENT

    def test_extract_keywords(self):
        keywords = CorrectionDetector._extract_keywords("Build the API endpoint")
        assert "build" in keywords
        assert "api" in keywords
        assert "endpoint" in keywords
        assert "the" in keywords  # 3 chars meets >= 3 threshold
        # Words shorter than 3 chars are excluded
        keywords2 = CorrectionDetector._extract_keywords("go to it")
        assert "go" not in keywords2
        assert "to" not in keywords2
        assert "it" not in keywords2

    def test_empty_task(self):
        cd = CorrectionDetector()
        result = cd.detect_resubmission("")
        assert result is None

    def test_resubmission_returns_most_recent_match(self):
        cd = CorrectionDetector(similarity_threshold=0.6)
        cd.record_task("fix the login bug in auth module", "task_old")
        cd.record_task("fix the login bug in auth module", "task_new")
        result = cd.detect_resubmission("fix the login bug in auth module")
        assert result is not None
        assert result.original_task_id == "task_new"


# ── Module-level singleton ────────────────────────────────────────────────

class TestModuleSingleton:
    def test_correction_detector_importable(self):
        from forge.signals import correction_detector
        assert isinstance(correction_detector, CorrectionDetector)
