"""
Tests for the structured eval framework.

Validates:
  - EvalCase and EvalScores data structures
  - Scoring functions (completion, correctness, efficiency, cost, safety)
  - EvalReport aggregation
  - Predefined eval cases
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.eval import (
    EvalCase,
    EvalScores,
    EvalResult,
    EvalReport,
    SMOKE_EVALS,
    score_completion,
    score_correctness,
    score_efficiency,
    score_cost,
    score_safety,
)
from forge.models import StepResult, TaskResult


# ── Scoring Function Tests ───────────────────────────────────────────────

class TestScoreCompletion:
    def test_all_success(self):
        tr = TaskResult(task_id="t1", task="test", results=[
            StepResult(step_number=1, status="success"),
            StepResult(step_number=2, status="success"),
        ])
        assert score_completion(tr) == 1.0

    def test_half_success(self):
        tr = TaskResult(task_id="t1", task="test", results=[
            StepResult(step_number=1, status="success"),
            StepResult(step_number=2, status="failed"),
        ])
        assert score_completion(tr) == 0.5

    def test_no_results(self):
        tr = TaskResult(task_id="t1", task="test", results=[])
        assert score_completion(tr) == 0.0

    def test_all_failed(self):
        tr = TaskResult(task_id="t1", task="test", results=[
            StepResult(step_number=1, status="failed"),
        ])
        assert score_completion(tr) == 0.0

    def test_mixed_statuses(self):
        tr = TaskResult(task_id="t1", task="test", results=[
            StepResult(step_number=1, status="success"),
            StepResult(step_number=2, status="failed"),
            StepResult(step_number=3, status="cancelled"),
            StepResult(step_number=4, status="success"),
        ])
        assert score_completion(tr) == 0.5


class TestScoreCorrectness:
    def test_all_expected_found(self):
        case = EvalCase(name="t", task="t", expected_outputs=["hello", "world"])
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", output="hello world test"),
        ])
        assert score_correctness(tr, case) == 1.0

    def test_none_found(self):
        case = EvalCase(name="t", task="t", expected_outputs=["hello", "world"])
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", output="nothing here"),
        ])
        assert score_correctness(tr, case) == 0.0

    def test_partial_found(self):
        case = EvalCase(name="t", task="t", expected_outputs=["hello", "world"])
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", output="hello there"),
        ])
        assert score_correctness(tr, case) == 0.5

    def test_no_expectations(self):
        case = EvalCase(name="t", task="t")
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", output="anything"),
        ])
        assert score_correctness(tr, case) == 1.0

    def test_case_insensitive(self):
        case = EvalCase(name="t", task="t", expected_outputs=["Hello"])
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", output="HELLO world"),
        ])
        assert score_correctness(tr, case) == 1.0


class TestScoreEfficiency:
    def test_under_budget(self):
        case = EvalCase(name="t", task="t", max_tool_calls=10)
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", tools_used=["a", "b", "c"]),
        ])
        assert score_efficiency(tr, case) == 1.0

    def test_at_budget(self):
        case = EvalCase(name="t", task="t", max_tool_calls=3)
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", tools_used=["a", "b", "c"]),
        ])
        assert score_efficiency(tr, case) == 1.0

    def test_double_budget(self):
        case = EvalCase(name="t", task="t", max_tool_calls=3)
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", tools_used=["a", "b", "c", "d", "e", "f"]),
        ])
        assert score_efficiency(tr, case) == 0.0

    def test_over_budget_partial(self):
        case = EvalCase(name="t", task="t", max_tool_calls=4)
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", tools_used=["a", "b", "c", "d", "e", "f"]),
        ])
        # 6/4 = 1.5 ratio, score = 1.0 - 0.5 = 0.5
        assert score_efficiency(tr, case) == 0.5

    def test_no_tools(self):
        case = EvalCase(name="t", task="t", max_tool_calls=5)
        tr = TaskResult(task_id="t1", task="t", results=[
            StepResult(step_number=1, status="success", tools_used=[]),
        ])
        assert score_efficiency(tr, case) == 0.5


class TestScoreCost:
    def test_under_budget(self):
        case = EvalCase(name="t", task="t", max_cost_usd=1.0)
        assert score_cost(0.5, case) == 1.0

    def test_at_budget(self):
        case = EvalCase(name="t", task="t", max_cost_usd=1.0)
        assert score_cost(1.0, case) == 1.0

    def test_triple_budget(self):
        case = EvalCase(name="t", task="t", max_cost_usd=1.0)
        assert score_cost(3.0, case) == 0.0

    def test_double_budget(self):
        case = EvalCase(name="t", task="t", max_cost_usd=1.0)
        assert score_cost(2.0, case) == 0.5

    def test_zero_cost(self):
        case = EvalCase(name="t", task="t", max_cost_usd=1.0)
        assert score_cost(0.0, case) == 1.0


class TestScoreSafety:
    def test_no_violations(self):
        assert score_safety(0) == 1.0

    def test_one_violation(self):
        assert score_safety(1) == 0.8

    def test_five_violations(self):
        assert score_safety(5) == 0.0

    def test_many_violations(self):
        assert score_safety(10) == 0.0


# ── EvalScores Tests ─────────────────────────────────────────────────────

class TestEvalScores:
    def test_perfect_scores(self):
        scores = EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0)
        assert scores.overall == 1.0

    def test_zero_scores(self):
        scores = EvalScores(completion=0.0, correctness=0.0, efficiency=0.0, cost=0.0, safety=0.0)
        assert scores.overall == 0.0

    def test_weighted_calculation(self):
        scores = EvalScores(completion=1.0, correctness=0.0, efficiency=0.0, cost=0.0, safety=0.0)
        assert scores.overall == 0.30  # completion weight


# ── EvalReport Tests ─────────────────────────────────────────────────────

class TestEvalReport:
    def test_empty_report(self):
        report = EvalReport()
        assert report.pass_rate == 0.0
        assert report.avg_scores == {}

    def test_pass_rate(self):
        report = EvalReport(results=[
            EvalResult(case_name="a", scores=EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0)),
            EvalResult(case_name="b", scores=EvalScores(completion=0.0, correctness=0.0, efficiency=0.0, cost=0.0, safety=0.0)),
        ])
        assert report.pass_rate == 0.5

    def test_all_pass(self):
        report = EvalReport(results=[
            EvalResult(case_name="a", scores=EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0)),
            EvalResult(case_name="b", scores=EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0)),
        ])
        assert report.pass_rate == 1.0

    def test_summary(self):
        report = EvalReport(results=[
            EvalResult(case_name="good", scores=EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0)),
            EvalResult(case_name="bad", scores=EvalScores(completion=0.0, correctness=0.0, efficiency=0.0, cost=0.0, safety=0.0)),
        ])
        summary = report.summary()
        assert summary["total_cases"] == 2
        assert summary["pass_rate"] == 0.5
        assert len(summary["failures"]) == 1
        assert summary["failures"][0]["case"] == "bad"

    def test_avg_scores(self):
        report = EvalReport(results=[
            EvalResult(case_name="a", scores=EvalScores(completion=1.0, correctness=0.8, efficiency=0.6, cost=1.0, safety=1.0)),
            EvalResult(case_name="b", scores=EvalScores(completion=0.5, correctness=0.2, efficiency=0.4, cost=0.5, safety=0.5)),
        ])
        avg = report.avg_scores
        assert avg["completion"] == 0.75
        assert avg["correctness"] == 0.5


# ── Predefined Evals Tests ──────────────────────────────────────────────

class TestSmokeEvals:
    def test_smoke_evals_exist(self):
        assert len(SMOKE_EVALS) >= 4

    def test_smoke_evals_have_names(self):
        for case in SMOKE_EVALS:
            assert case.name
            assert case.task

    def test_smoke_evals_have_tags(self):
        for case in SMOKE_EVALS:
            assert "smoke" in case.tags

    def test_smoke_evals_have_budgets(self):
        for case in SMOKE_EVALS:
            assert case.max_tool_calls > 0
            assert case.max_cost_usd > 0
