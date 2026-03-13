"""
Tests for the PRM Judge — OpenClaw-RL (arXiv:2603.10165).

Covers: JudgeScore, StepJudge (parse logic), BackgroundJudge lifecycle.
LLM calls are mocked to avoid real API hits.
"""
import json
import time
from unittest.mock import patch, MagicMock

import pytest

from forge.judge import JudgeScore, StepJudge, BackgroundJudge
from forge.models import PlanStep, StepResult


# ── JudgeScore ────────────────────────────────────────────────────────────

class TestJudgeScore:
    def test_defaults(self):
        js = JudgeScore(step_number=1, score=7.5)
        assert js.step_number == 1
        assert js.score == 7.5
        assert js.rationale == ""
        assert js.judge_model == ""
        assert js.cost_usd == 0.0

    def test_full_fields(self):
        js = JudgeScore(
            step_number=3, score=9.0, rationale="Excellent",
            judge_model="grok-4-1-fast-reasoning", latency_seconds=1.2, cost_usd=0.0001,
        )
        assert js.rationale == "Excellent"
        assert js.judge_model == "grok-4-1-fast-reasoning"


# ── StepJudge._parse_response ─────────────────────────────────────────────

class TestStepJudgeParser:
    def test_parse_valid_json(self):
        result = StepJudge._parse_response('{"score": 8, "rationale": "Good work"}')
        assert result["score"] == 8.0
        assert result["rationale"] == "Good work"

    def test_parse_markdown_code_block(self):
        text = '```json\n{"score": 6, "rationale": "Adequate"}\n```'
        result = StepJudge._parse_response(text)
        assert result["score"] == 6.0

    def test_parse_clamps_high(self):
        result = StepJudge._parse_response('{"score": 15, "rationale": "over"}')
        assert result["score"] == 10.0

    def test_parse_clamps_low(self):
        result = StepJudge._parse_response('{"score": -5, "rationale": "under"}')
        assert result["score"] == 0.0

    def test_parse_missing_score(self):
        result = StepJudge._parse_response('{"rationale": "no score"}')
        assert result["score"] == 5.0  # default

    def test_parse_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            StepJudge._parse_response("not json at all")

    def test_parse_truncates_long_rationale(self):
        long_rationale = "x" * 300
        result = StepJudge._parse_response(json.dumps({"score": 5, "rationale": long_rationale}))
        assert len(result["rationale"]) <= 200


# ── StepJudge.judge_step (mocked LLM) ────────────────────────────────────

class TestStepJudge:
    @patch.object(StepJudge, "_call_llm")
    def test_judge_step_success(self, mock_llm):
        mock_llm.return_value = '{"score": 8.5, "rationale": "Well done"}'
        judge = StepJudge(model="test-model")
        step = PlanStep(step_number=1, title="Read file", description="Read config.py")
        result = StepResult(step_number=1, status="success", output="file contents")

        score = judge.judge_step(step, result, "fix the bug")
        assert score.step_number == 1
        assert score.score == 8.5
        assert score.rationale == "Well done"
        assert score.judge_model == "test-model"
        assert score.latency_seconds >= 0.0

    @patch.object(StepJudge, "_call_llm")
    def test_judge_step_llm_failure(self, mock_llm):
        mock_llm.side_effect = Exception("API timeout")
        judge = StepJudge()
        step = PlanStep(step_number=2, title="Write", description="Write code")
        result = StepResult(step_number=2, status="failed", error="timeout")

        score = judge.judge_step(step, result, "build feature")
        assert score.step_number == 2
        assert score.score == 5.0  # neutral fallback
        assert "Judge error" in score.rationale

    @patch.object(StepJudge, "_call_llm")
    def test_judge_step_parse_failure(self, mock_llm):
        mock_llm.return_value = "This is not JSON"
        judge = StepJudge()
        step = PlanStep(step_number=1, title="Step", description="Do thing")
        result = StepResult(step_number=1, status="success", output="ok")

        score = judge.judge_step(step, result, "task")
        assert score.score == 5.0  # neutral fallback on parse error


# ── BackgroundJudge ───────────────────────────────────────────────────────

class TestBackgroundJudge:
    def test_submit_and_collect(self):
        mock_score = JudgeScore(step_number=1, score=7.0, rationale="Good", judge_model="test")
        with patch.object(StepJudge, "judge_step", return_value=mock_score):
            bg = BackgroundJudge(model="test-model")
            step = PlanStep(step_number=1, title="Step 1", description="Do A")
            result = StepResult(step_number=1, status="success", output="done")
            bg.submit(step, result, "test task")

            time.sleep(1.0)
            scores = bg.collect()
            bg.shutdown()

            assert len(scores) >= 1
            assert scores[0].score == 7.0

    def test_multiple_submissions(self):
        def fake_judge(step, result, task_goal):
            return JudgeScore(step_number=step.step_number, score=6.0, rationale="Ok")

        with patch.object(StepJudge, "judge_step", side_effect=fake_judge):
            bg = BackgroundJudge(model="test-model")
            for i in range(3):
                step = PlanStep(step_number=i + 1, title=f"Step {i+1}", description=f"Task {i+1}")
                result = StepResult(step_number=i + 1, status="success", output="output")
                bg.submit(step, result, "multi test")

            time.sleep(2.0)
            scores = bg.collect()
            bg.shutdown()

            assert len(scores) == 3
            for s in scores:
                assert s.score == 6.0

    def test_collect_empty(self):
        with patch.object(StepJudge, "judge_step", return_value=JudgeScore(step_number=1, score=5.0)):
            bg = BackgroundJudge(model="test-model")
            scores = bg.collect()
            bg.shutdown()
            assert scores == []

    def test_shutdown_idempotent(self):
        with patch.object(StepJudge, "judge_step", return_value=JudgeScore(step_number=1, score=5.0)):
            bg = BackgroundJudge(model="test-model")
            bg.shutdown()
            bg.shutdown()  # should not raise
