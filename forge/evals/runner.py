"""
Extended EvalRunner — pack-scoped runs, chaos mode, cross-provider benchmarks.

Builds on forge.eval.EvalRunner with:
  - Pack-scoped execution (tool filtering, budget, guardrails from pack)
  - Chaos mode: inject random provider timeouts and failures
  - Cross-provider benchmarks: run same eval across multiple models
  - Pack readiness gating: skip evals for unavailable packs
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from forge.eval import (
    EvalCase, EvalResult, EvalReport, EvalScores,
    score_completion, score_correctness, score_efficiency,
    score_cost, score_safety, EVAL_DIR,
)
from forge.evals.golden import PACK_GOLDEN_MAP, get_golden_evals

log = logging.getLogger("forge.evals.runner")


@dataclass
class ChaosConfig:
    """Configuration for chaos mode — simulates provider instability."""
    enabled: bool = False
    failure_rate: float = 0.15        # probability of injecting a failure per step
    timeout_rate: float = 0.10        # probability of injecting a timeout per step
    timeout_seconds: float = 5.0      # max simulated timeout duration
    error_messages: list[str] = field(default_factory=lambda: [
        "Provider timeout: upstream model did not respond within deadline",
        "Rate limit exceeded: retry after 30s",
        "Internal server error: model inference failed",
        "Connection reset by peer: provider unreachable",
        "Token budget exhausted: request too large for context window",
    ])
    seed: int | None = None           # for reproducible chaos

    def should_fail(self, rng: random.Random) -> bool:
        return rng.random() < self.failure_rate

    def should_timeout(self, rng: random.Random) -> bool:
        return rng.random() < self.timeout_rate

    def get_error(self, rng: random.Random) -> str:
        return rng.choice(self.error_messages)

    def get_timeout(self, rng: random.Random) -> float:
        return rng.uniform(0.5, self.timeout_seconds)


@dataclass
class BenchmarkResult:
    """Result of running the same eval across multiple providers."""
    case_name: str
    pack_name: str
    results_by_model: dict[str, EvalResult] = field(default_factory=dict)
    timestamp: str = ""

    def best_model(self) -> str:
        if not self.results_by_model:
            return ""
        return max(self.results_by_model, key=lambda m: self.results_by_model[m].scores.overall)

    def to_dict(self) -> dict:
        return {
            "case_name": self.case_name,
            "pack_name": self.pack_name,
            "timestamp": self.timestamp,
            "best_model": self.best_model(),
            "models": {
                model: {
                    "overall": round(r.scores.overall, 3),
                    "completion": round(r.scores.completion, 3),
                    "correctness": round(r.scores.correctness, 3),
                    "efficiency": round(r.scores.efficiency, 3),
                    "cost": round(r.scores.cost, 3),
                    "safety": round(r.scores.safety, 3),
                    "duration_seconds": r.duration_seconds,
                    "cost_usd": r.cost_usd,
                    "error": r.error,
                }
                for model, r in self.results_by_model.items()
            },
        }


class PackEvalRunner:
    """Extended eval runner with pack-scoping, chaos mode, and benchmarks."""

    def __init__(
        self,
        sandbox_path: str = "",
        chaos: ChaosConfig | None = None,
    ):
        self.sandbox_path = sandbox_path
        self.chaos = chaos or ChaosConfig()
        self._rng = random.Random(self.chaos.seed)

    def run_pack_eval(self, pack_name: str, cases: list[EvalCase] | None = None) -> EvalReport:
        """Run golden evals for a specific pack with pack-scoped execution.

        If cases is None, uses the golden eval cases for the pack.
        Returns EvalReport with results and readiness info.
        """
        from forge.packs import get_registry

        registry = get_registry()
        pack = registry.get(pack_name)
        if not pack:
            log.error("Unknown pack: %s", pack_name)
            return EvalReport(
                results=[],
                timestamp=datetime.now().isoformat(),
            )

        # Check readiness — warn but don't block (eval can test degraded states)
        readiness = pack.check_readiness()
        if readiness.state == "unavailable":
            log.warning("Pack %s is unavailable: %s — eval may fail", pack_name,
                        [c.message for c in readiness.checks if c.status != "ok"])

        # Get eval cases
        if cases is None:
            cases = get_golden_evals(pack_name)
        if not cases:
            log.warning("No golden eval cases found for pack: %s", pack_name)
            return EvalReport(results=[], timestamp=datetime.now().isoformat())

        log.info("Running pack eval: %s (%d cases, readiness=%s)",
                 pack_name, len(cases), readiness.state)

        results = []
        for case in cases:
            result = self._run_case_with_pack(case, pack_name)
            results.append(result)

        report = EvalReport(
            results=results,
            timestamp=datetime.now().isoformat(),
        )

        # Save report
        self._save_report(report, pack_name)

        log.info("Pack eval %s complete: pass_rate=%.1f%% avg_overall=%.3f",
                 pack_name, report.pass_rate * 100,
                 report.avg_scores.get("overall", 0))

        return report

    def run_benchmark(self, pack_name: str, models: list[str],
                      case: EvalCase | None = None) -> BenchmarkResult:
        """Run the same eval case across multiple models for comparison."""
        if case is None:
            case = PACK_GOLDEN_MAP.get(pack_name)
            if not case:
                log.error("No golden eval case for pack: %s", pack_name)
                return BenchmarkResult(
                    case_name="", pack_name=pack_name,
                    timestamp=datetime.now().isoformat(),
                )

        log.info("Running benchmark for %s across %d models", pack_name, len(models))

        benchmark = BenchmarkResult(
            case_name=case.name,
            pack_name=pack_name,
            timestamp=datetime.now().isoformat(),
        )

        for model in models:
            log.info("  Benchmarking model: %s", model)
            result = self._run_case_with_pack(case, pack_name, executor_model=model)
            benchmark.results_by_model[model] = result

        log.info("Benchmark complete. Best model: %s", benchmark.best_model())
        return benchmark

    def _run_case_with_pack(self, case: EvalCase, pack_name: str,
                            executor_model: str = "") -> EvalResult:
        """Run a single eval case with pack-scoped orchestrator + optional chaos."""
        from forge.orchestrator import Orchestrator

        start = time.time()
        cancel = threading.Event()

        orch = Orchestrator(
            sandbox_path=self.sandbox_path,
            direct_mode=False,
            cancel_event=cancel,
            executor_model=executor_model,
            pack=pack_name,
        )

        task_result = None
        cost_usd = 0.0
        guardrail_violations = 0
        error = None
        chaos_injections = 0

        try:
            gen = orch.run(case.task)
            while True:
                # Chaos mode: inject failures before processing next message
                if self.chaos.enabled:
                    if self.chaos.should_fail(self._rng):
                        chaos_injections += 1
                        err_msg = self.chaos.get_error(self._rng)
                        log.warning("CHAOS: injecting failure — %s", err_msg)
                        error = f"[CHAOS] {err_msg}"
                        break
                    if self.chaos.should_timeout(self._rng):
                        chaos_injections += 1
                        delay = self.chaos.get_timeout(self._rng)
                        log.warning("CHAOS: injecting %.1fs timeout", delay)
                        time.sleep(delay)

                try:
                    msg = next(gen)
                    if msg.get("type") == "token_usage":
                        cost_usd += msg.get("cost_usd", 0)
                    elif msg.get("type") == "guardrail_violation":
                        guardrail_violations += 1
                    elif msg.get("type") == "error":
                        error = msg.get("content", "Unknown error")
                except StopIteration as e:
                    task_result = e.value
                    break
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.error("Pack eval %s/%s failed: %s", pack_name, case.name, error)

        duration = time.time() - start

        # Score
        if task_result:
            completion = score_completion(task_result)
            correctness = score_correctness(task_result, case)
            efficiency = score_efficiency(task_result, case)
        else:
            completion = 0.0
            correctness = 0.0
            efficiency = 0.0

        scores = EvalScores(
            completion=completion,
            correctness=correctness,
            efficiency=efficiency,
            cost=score_cost(cost_usd, case),
            safety=score_safety(guardrail_violations),
        )

        total_calls = sum(len(r.tools_used) for r in task_result.results) if task_result else 0

        result = EvalResult(
            case_name=case.name,
            scores=scores,
            task_result=task_result,
            duration_seconds=round(duration, 2),
            error=error,
            tool_calls_total=total_calls,
            cost_usd=round(cost_usd, 6),
            guardrail_violations=guardrail_violations,
        )

        log.info("  %s/%s: overall=%.3f chaos_injections=%d (%.1fs)",
                 pack_name, case.name, scores.overall, chaos_injections, duration)

        return result

    def _save_report(self, report: EvalReport, pack_name: str):
        """Save pack eval report to disk."""
        import json
        ts = report.timestamp.replace(":", "-")
        report_path = EVAL_DIR / f"pack_eval_{pack_name}_{ts}.json"
        report_data = {
            "pack": pack_name,
            "timestamp": report.timestamp,
            "summary": report.summary(),
            "results": [
                {
                    "case_name": r.case_name,
                    "scores": {
                        "completion": r.scores.completion,
                        "correctness": r.scores.correctness,
                        "efficiency": r.scores.efficiency,
                        "cost": r.scores.cost,
                        "safety": r.scores.safety,
                        "overall": r.scores.overall,
                    },
                    "duration_seconds": r.duration_seconds,
                    "tool_calls_total": r.tool_calls_total,
                    "cost_usd": r.cost_usd,
                    "guardrail_violations": r.guardrail_violations,
                    "error": r.error,
                }
                for r in report.results
            ],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        log.info("Pack eval report saved: %s", report_path)
