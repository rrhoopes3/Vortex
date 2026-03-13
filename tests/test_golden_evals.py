"""
Tests for Phase 4: Golden evals, pack-scoped runner, chaos mode, benchmarks.

Validates:
  - Golden eval case definitions (all 6 packs + arena extras)
  - PackEvalRunner initialization and pack gating
  - ChaosConfig injection logic
  - BenchmarkResult aggregation
  - Pack eval API endpoint wiring
  - get_golden_evals() filtering
"""
import os
import sys
import random
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.eval import EvalCase, EvalScores, EvalResult, EvalReport
from forge.evals.golden import (
    ALL_GOLDEN_EVALS,
    PACK_GOLDEN_MAP,
    RESEARCH_GOLDEN,
    BUILDER_GOLDEN,
    OPS_GOLDEN,
    TRADING_GOLDEN,
    ARENA_GOLDEN,
    EMAIL_GOLDEN,
    ARENA_COMBAT_SMOKE,
    ARENA_MARKETPLACE_RELAY,
    get_golden_evals,
)
from forge.evals.runner import ChaosConfig, BenchmarkResult, PackEvalRunner


# ── Golden Eval Case Definitions ────────────────────────────────────────────


class TestGoldenEvalCases:
    """Validate all golden eval case definitions."""

    def test_all_golden_evals_exist(self):
        assert len(ALL_GOLDEN_EVALS) == 8  # 6 packs + 2 arena extras

    def test_pack_golden_map_has_all_packs(self):
        expected = {"research", "builder", "ops", "trading", "arena", "email"}
        assert set(PACK_GOLDEN_MAP.keys()) == expected

    def test_every_golden_has_name_and_task(self):
        for case in ALL_GOLDEN_EVALS:
            assert case.name, f"Golden eval missing name"
            assert case.task, f"Golden eval {case.name} missing task"
            assert len(case.task) > 20, f"Golden eval {case.name} task too short"

    def test_every_golden_has_tags(self):
        for case in ALL_GOLDEN_EVALS:
            assert "golden" in case.tags, f"{case.name} missing 'golden' tag"

    def test_every_golden_has_expected_outputs(self):
        for case in ALL_GOLDEN_EVALS:
            assert len(case.expected_outputs) >= 1, f"{case.name} needs expected outputs"

    def test_every_golden_has_budget(self):
        for case in ALL_GOLDEN_EVALS:
            assert case.max_cost_usd > 0, f"{case.name} needs cost budget"
            assert case.max_steps > 0, f"{case.name} needs step budget"
            assert case.max_tool_calls > 0, f"{case.name} needs tool call budget"

    def test_research_golden_specifics(self):
        assert RESEARCH_GOLDEN.name == "golden_research"
        assert "quantum" in RESEARCH_GOLDEN.expected_outputs
        assert RESEARCH_GOLDEN.max_cost_usd == 2.0
        assert RESEARCH_GOLDEN.max_steps == 10

    def test_builder_golden_specifics(self):
        assert BUILDER_GOLDEN.name == "golden_builder"
        assert "write_file" in BUILDER_GOLDEN.expected_tools
        assert BUILDER_GOLDEN.max_cost_usd == 5.0
        assert len(BUILDER_GOLDEN.expected_files) > 0

    def test_trading_golden_specifics(self):
        assert TRADING_GOLDEN.name == "golden_trading"
        assert "SPY" in TRADING_GOLDEN.expected_outputs
        assert TRADING_GOLDEN.max_cost_usd == 1.0  # tight budget
        assert TRADING_GOLDEN.max_steps == 5

    def test_arena_golden_specifics(self):
        assert ARENA_GOLDEN.name == "golden_arena"
        assert ARENA_GOLDEN.max_cost_usd == 10.0  # generous for arena

    def test_arena_extras_exist(self):
        assert ARENA_COMBAT_SMOKE.name == "arena_combat_smoke"
        assert ARENA_MARKETPLACE_RELAY.name == "arena_marketplace_relay"
        assert "smoke" in ARENA_COMBAT_SMOKE.tags
        assert "marketplace" in ARENA_MARKETPLACE_RELAY.tags


# ── get_golden_evals() Filtering ────────────────────────────────────────────


class TestGetGoldenEvals:
    """Test golden eval filtering by pack name."""

    def test_no_filter_returns_all(self):
        cases = get_golden_evals()
        assert len(cases) == 8

    def test_filter_by_research(self):
        cases = get_golden_evals("research")
        assert len(cases) == 1
        assert cases[0].name == "golden_research"

    def test_filter_by_trading(self):
        cases = get_golden_evals("trading")
        assert len(cases) == 1
        assert cases[0].name == "golden_trading"

    def test_filter_by_arena_gets_all_arena(self):
        cases = get_golden_evals("arena")
        assert len(cases) == 3  # golden_arena + combat_smoke + marketplace_relay
        names = {c.name for c in cases}
        assert "golden_arena" in names
        assert "arena_combat_smoke" in names
        assert "arena_marketplace_relay" in names

    def test_filter_unknown_pack_returns_empty(self):
        cases = get_golden_evals("nonexistent")
        assert len(cases) == 0


# ── ChaosConfig ─────────────────────────────────────────────────────────────


class TestChaosConfig:
    """Test chaos mode injection logic."""

    def test_default_chaos_disabled(self):
        chaos = ChaosConfig()
        assert not chaos.enabled
        assert chaos.failure_rate == 0.15
        assert chaos.timeout_rate == 0.10

    def test_chaos_seeded_deterministic(self):
        chaos = ChaosConfig(enabled=True, seed=42)
        rng = random.Random(42)
        results1 = [chaos.should_fail(rng) for _ in range(100)]

        rng2 = random.Random(42)
        results2 = [chaos.should_fail(rng2) for _ in range(100)]

        assert results1 == results2

    def test_failure_rate_zero_never_fails(self):
        chaos = ChaosConfig(enabled=True, failure_rate=0.0)
        rng = random.Random(1)
        assert not any(chaos.should_fail(rng) for _ in range(100))

    def test_failure_rate_one_always_fails(self):
        chaos = ChaosConfig(enabled=True, failure_rate=1.0)
        rng = random.Random(1)
        assert all(chaos.should_fail(rng) for _ in range(100))

    def test_timeout_rate_respects_bounds(self):
        chaos = ChaosConfig(enabled=True, timeout_seconds=3.0)
        rng = random.Random(42)
        timeouts = [chaos.get_timeout(rng) for _ in range(50)]
        assert all(0.5 <= t <= 3.0 for t in timeouts)

    def test_get_error_returns_valid_message(self):
        chaos = ChaosConfig(enabled=True)
        rng = random.Random(42)
        for _ in range(20):
            msg = chaos.get_error(rng)
            assert isinstance(msg, str)
            assert len(msg) > 10
            assert msg in chaos.error_messages

    def test_chaos_with_custom_errors(self):
        chaos = ChaosConfig(
            enabled=True,
            error_messages=["custom error 1", "custom error 2"],
        )
        rng = random.Random(42)
        msg = chaos.get_error(rng)
        assert msg in ["custom error 1", "custom error 2"]


# ── BenchmarkResult ─────────────────────────────────────────────────────────


class TestBenchmarkResult:
    """Test cross-provider benchmark result aggregation."""

    def _make_result(self, overall: float, cost: float = 0.01) -> EvalResult:
        return EvalResult(
            case_name="test",
            scores=EvalScores(
                completion=overall,
                correctness=overall,
                efficiency=overall,
                cost=overall,
                safety=1.0,
            ),
            cost_usd=cost,
        )

    def test_empty_benchmark(self):
        b = BenchmarkResult(case_name="test", pack_name="research")
        assert b.best_model() == ""
        d = b.to_dict()
        assert d["best_model"] == ""
        assert d["models"] == {}

    def test_single_model(self):
        b = BenchmarkResult(
            case_name="test", pack_name="research",
            results_by_model={"grok-4.1": self._make_result(0.8)},
        )
        assert b.best_model() == "grok-4.1"

    def test_best_model_selection(self):
        b = BenchmarkResult(
            case_name="test", pack_name="research",
            results_by_model={
                "grok-4.1": self._make_result(0.6),
                "claude-sonnet": self._make_result(0.9),
                "gpt-4o": self._make_result(0.7),
            },
        )
        assert b.best_model() == "claude-sonnet"

    def test_to_dict_structure(self):
        b = BenchmarkResult(
            case_name="golden_research", pack_name="research",
            timestamp="2026-03-13T12:00:00",
            results_by_model={
                "model_a": self._make_result(0.8, cost=0.05),
                "model_b": self._make_result(0.6, cost=0.02),
            },
        )
        d = b.to_dict()
        assert d["case_name"] == "golden_research"
        assert d["pack_name"] == "research"
        assert d["timestamp"] == "2026-03-13T12:00:00"
        assert d["best_model"] == "model_a"
        assert "model_a" in d["models"]
        assert "model_b" in d["models"]
        assert d["models"]["model_a"]["cost_usd"] == 0.05

    def test_tied_models_picks_first_max(self):
        b = BenchmarkResult(
            case_name="test", pack_name="ops",
            results_by_model={
                "a": self._make_result(0.8),
                "b": self._make_result(0.8),
            },
        )
        # With equal scores, max() picks one deterministically
        assert b.best_model() in ("a", "b")


# ── PackEvalRunner ──────────────────────────────────────────────────────────


class TestPackEvalRunner:
    """Test pack eval runner initialization and gating."""

    def test_init_defaults(self):
        runner = PackEvalRunner()
        assert runner.sandbox_path == ""
        assert not runner.chaos.enabled

    def test_init_with_chaos(self):
        chaos = ChaosConfig(enabled=True, failure_rate=0.5, seed=42)
        runner = PackEvalRunner(chaos=chaos)
        assert runner.chaos.enabled
        assert runner.chaos.failure_rate == 0.5
        assert runner.chaos.seed == 42

    @patch("forge.evals.runner.PackEvalRunner._run_case_with_pack")
    @patch("forge.packs.get_registry")
    def test_run_pack_eval_unknown_pack(self, mock_registry, mock_run):
        mock_reg = MagicMock()
        mock_reg.get.return_value = None
        mock_registry.return_value = mock_reg

        runner = PackEvalRunner()
        report = runner.run_pack_eval("nonexistent")
        assert len(report.results) == 0
        mock_run.assert_not_called()

    @patch("forge.evals.runner.PackEvalRunner._run_case_with_pack")
    @patch("forge.packs.get_registry")
    def test_run_pack_eval_with_pack(self, mock_registry, mock_run):
        mock_pack = MagicMock()
        mock_pack.check_readiness.return_value = MagicMock(state="ready", checks=[])
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_pack
        mock_registry.return_value = mock_reg

        mock_run.return_value = EvalResult(
            case_name="golden_research",
            scores=EvalScores(completion=1.0, correctness=1.0, efficiency=1.0, cost=1.0, safety=1.0),
        )

        runner = PackEvalRunner()
        report = runner.run_pack_eval("research")
        assert len(report.results) == 1
        assert report.results[0].case_name == "golden_research"

    @patch("forge.evals.runner.PackEvalRunner._run_case_with_pack")
    @patch("forge.packs.get_registry")
    def test_run_benchmark_multiple_models(self, mock_registry, mock_run):
        mock_pack = MagicMock()
        mock_pack.check_readiness.return_value = MagicMock(state="ready", checks=[])
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_pack
        mock_registry.return_value = mock_reg

        call_count = [0]
        def fake_run(case, pack, executor_model=""):
            call_count[0] += 1
            score = 0.9 if "grok" in executor_model else 0.7
            return EvalResult(
                case_name=case.name,
                scores=EvalScores(completion=score, correctness=score),
            )
        mock_run.side_effect = fake_run

        runner = PackEvalRunner()
        benchmark = runner.run_benchmark("research", ["grok-4.1", "claude-sonnet"])
        assert len(benchmark.results_by_model) == 2
        assert benchmark.best_model() == "grok-4.1"
        assert call_count[0] == 2


# ── Chaos Mode Integration ─────────────────────────────────────────────────


class TestChaosIntegration:
    """Test chaos mode with deterministic seeds."""

    def test_chaos_produces_failures_at_high_rate(self):
        chaos = ChaosConfig(enabled=True, failure_rate=1.0, seed=42)
        rng = random.Random(42)
        # With 100% failure rate, every check should fail
        failures = sum(1 for _ in range(10) if chaos.should_fail(rng))
        assert failures == 10

    def test_chaos_disabled_no_failures(self):
        chaos = ChaosConfig(enabled=False, failure_rate=1.0)
        # Even with 100% rate, should_fail still works but caller checks .enabled
        assert not chaos.enabled

    def test_chaos_timeout_range(self):
        chaos = ChaosConfig(enabled=True, timeout_seconds=2.0, seed=99)
        rng = random.Random(99)
        timeouts = [chaos.get_timeout(rng) for _ in range(50)]
        assert min(timeouts) >= 0.5
        assert max(timeouts) <= 2.0

    def test_chaos_reproducible_sequence(self):
        """Same seed produces same failure/timeout sequence."""
        chaos = ChaosConfig(enabled=True, seed=123, failure_rate=0.3, timeout_rate=0.2)

        rng1 = random.Random(123)
        seq1 = [(chaos.should_fail(rng1), chaos.should_timeout(rng1)) for _ in range(20)]

        rng2 = random.Random(123)
        seq2 = [(chaos.should_fail(rng2), chaos.should_timeout(rng2)) for _ in range(20)]

        assert seq1 == seq2


# ── Pack-Specific Golden Eval Alignment ─────────────────────────────────────


class TestPackEvalAlignment:
    """Verify golden evals align with their pack definitions."""

    def test_trading_budget_matches_pack(self):
        """Trading golden eval budget should not exceed pack budget."""
        assert TRADING_GOLDEN.max_cost_usd <= 1.0
        assert TRADING_GOLDEN.max_steps <= 5

    def test_builder_budget_matches_pack(self):
        assert BUILDER_GOLDEN.max_cost_usd <= 5.0
        assert BUILDER_GOLDEN.max_steps <= 15

    def test_arena_budget_matches_pack(self):
        assert ARENA_GOLDEN.max_cost_usd <= 10.0
        assert ARENA_GOLDEN.max_steps <= 20

    def test_ops_budget_matches_pack(self):
        assert OPS_GOLDEN.max_cost_usd <= 3.0
        assert OPS_GOLDEN.max_steps <= 10

    def test_email_budget_matches_pack(self):
        assert EMAIL_GOLDEN.max_cost_usd <= 1.0
        assert EMAIL_GOLDEN.max_steps <= 5

    def test_research_budget_matches_pack(self):
        assert RESEARCH_GOLDEN.max_cost_usd <= 2.0
        assert RESEARCH_GOLDEN.max_steps <= 10
