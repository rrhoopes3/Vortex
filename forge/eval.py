"""
Structured Eval Framework — end-to-end agent task scoring.

Inspired by OpenAI's "A Practical Guide to Building Agents" emphasis on
building systematic evaluation harnesses early.

Provides:
  1. EvalCase    — defines a task + expected outcomes + scoring criteria
  2. EvalResult  — structured result with multi-dimensional scores
  3. EvalRunner  — runs eval cases through the orchestrator and scores them
  4. EvalReport  — aggregate report across multiple eval runs

Scoring dimensions:
  - completion: did the agent finish the task? (0.0-1.0)
  - correctness: did the output match expected outcomes? (0.0-1.0)
  - efficiency: tool calls used vs. expected (0.0-1.0)
  - cost: USD spent vs. budget (0.0-1.0)
  - safety: guardrail violations count (0.0-1.0)
"""
from __future__ import annotations
import json
import logging
import re
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from forge.config import DATA_DIR
from forge.models import TaskResult

log = logging.getLogger("forge.eval")

EVAL_DIR = DATA_DIR / "evals"
EVAL_DIR.mkdir(exist_ok=True)


# ── Data Structures ──────────────────────────────────────────────────────


@dataclass
class EvalCase:
    """A single evaluation case."""
    name: str
    task: str
    expected_outputs: list[str] = field(default_factory=list)  # substrings expected in output
    expected_files: list[str] = field(default_factory=list)     # files that should exist after
    expected_tools: list[str] = field(default_factory=list)     # tools expected to be used
    max_tool_calls: int = 20                                     # efficiency budget
    max_cost_usd: float = 1.0                                   # cost budget
    max_steps: int = 5                                           # step budget
    tags: list[str] = field(default_factory=list)                # for filtering
    custom_validators: list[Callable[[TaskResult], float]] = field(default_factory=list)


@dataclass
class EvalScores:
    """Multi-dimensional scores for a single eval run."""
    completion: float = 0.0    # 0.0-1.0
    correctness: float = 0.0   # 0.0-1.0
    efficiency: float = 0.0    # 0.0-1.0
    cost: float = 0.0          # 0.0-1.0
    safety: float = 1.0        # 0.0-1.0 (starts at 1, penalized by violations)

    @property
    def overall(self) -> float:
        """Weighted overall score."""
        return (
            self.completion * 0.30
            + self.correctness * 0.30
            + self.efficiency * 0.15
            + self.cost * 0.10
            + self.safety * 0.15
        )


@dataclass
class EvalResult:
    """Result of running a single eval case."""
    case_name: str
    scores: EvalScores
    task_result: TaskResult | None = None
    duration_seconds: float = 0.0
    error: str | None = None
    tool_calls_total: int = 0
    cost_usd: float = 0.0
    guardrail_violations: int = 0


@dataclass
class EvalReport:
    """Aggregate report across multiple eval results."""
    results: list[EvalResult] = field(default_factory=list)
    timestamp: str = ""

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.scores.overall >= 0.6)
        return passed / len(self.results)

    @property
    def avg_scores(self) -> dict[str, float]:
        if not self.results:
            return {}
        n = len(self.results)
        return {
            "completion": sum(r.scores.completion for r in self.results) / n,
            "correctness": sum(r.scores.correctness for r in self.results) / n,
            "efficiency": sum(r.scores.efficiency for r in self.results) / n,
            "cost": sum(r.scores.cost for r in self.results) / n,
            "safety": sum(r.scores.safety for r in self.results) / n,
            "overall": sum(r.scores.overall for r in self.results) / n,
        }

    def summary(self) -> dict:
        return {
            "total_cases": len(self.results),
            "pass_rate": round(self.pass_rate, 3),
            "avg_scores": {k: round(v, 3) for k, v in self.avg_scores.items()},
            "failures": [
                {"case": r.case_name, "overall": round(r.scores.overall, 3), "error": r.error}
                for r in self.results if r.scores.overall < 0.6
            ],
        }


# ── Scoring Functions ────────────────────────────────────────────────────


def score_completion(task_result: TaskResult) -> float:
    """Score task completion (0.0-1.0)."""
    if not task_result.results:
        return 0.0
    success_count = sum(1 for r in task_result.results if r.status == "success")
    return success_count / len(task_result.results)


def score_correctness(task_result: TaskResult, case: EvalCase) -> float:
    """Score output correctness based on expected outputs."""
    if not case.expected_outputs:
        # No expectations defined — full marks if completed
        return 1.0 if score_completion(task_result) > 0 else 0.0

    all_output = " ".join(r.output for r in task_result.results)
    matches = sum(
        1 for expected in case.expected_outputs
        if expected.lower() in all_output.lower()
    )
    return matches / len(case.expected_outputs)


def score_efficiency(task_result: TaskResult, case: EvalCase) -> float:
    """Score efficiency: fewer tool calls relative to budget = better."""
    total_calls = sum(len(r.tools_used) for r in task_result.results)
    if case.max_tool_calls <= 0:
        return 1.0
    if total_calls == 0:
        return 0.5  # completed without tools — ambiguous
    # Score: 1.0 if at or under budget, degrades linearly beyond 2x budget
    ratio = total_calls / case.max_tool_calls
    if ratio <= 1.0:
        return 1.0
    elif ratio >= 2.0:
        return 0.0
    else:
        return 1.0 - (ratio - 1.0)


def score_cost(cost_usd: float, case: EvalCase) -> float:
    """Score cost efficiency: under budget = 1.0, linearly degrades."""
    if case.max_cost_usd <= 0:
        return 1.0
    if cost_usd <= 0:
        return 1.0
    ratio = cost_usd / case.max_cost_usd
    if ratio <= 1.0:
        return 1.0
    elif ratio >= 3.0:
        return 0.0
    else:
        return 1.0 - (ratio - 1.0) / 2.0


def score_safety(guardrail_violations: int) -> float:
    """Score safety: each violation reduces score."""
    if guardrail_violations == 0:
        return 1.0
    # Each violation reduces score by 0.2, floor at 0.0
    return max(0.0, 1.0 - guardrail_violations * 0.2)


# ── Eval Runner ──────────────────────────────────────────────────────────


class EvalRunner:
    """Runs eval cases through the orchestrator and produces scored results."""

    def __init__(
        self,
        sandbox_path: str = "",
        executor_model: str = "",
        direct_mode: bool = False,
    ):
        self.sandbox_path = sandbox_path
        self.executor_model = executor_model
        self.direct_mode = direct_mode

    def run_case(self, case: EvalCase) -> EvalResult:
        """Run a single eval case and score it."""
        from forge.orchestrator import Orchestrator

        log.info("Running eval case: %s", case.name)
        start = time.time()

        cancel = threading.Event()
        orch = Orchestrator(
            sandbox_path=self.sandbox_path,
            direct_mode=self.direct_mode,
            cancel_event=cancel,
            executor_model=self.executor_model,
        )

        task_result = None
        cost_usd = 0.0
        guardrail_violations = 0
        error = None

        try:
            gen = orch.run(case.task)
            while True:
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
            log.error("Eval case %s failed: %s", case.name, error)

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

        log.info("Eval case %s: overall=%.3f completion=%.2f correctness=%.2f efficiency=%.2f cost=%.2f safety=%.2f (%.1fs, $%.4f)",
                 case.name, scores.overall, scores.completion, scores.correctness,
                 scores.efficiency, scores.cost, scores.safety, duration, cost_usd)

        return result

    def run_suite(self, cases: list[EvalCase], tags: list[str] | None = None) -> EvalReport:
        """Run multiple eval cases and produce an aggregate report.

        If tags is provided, only run cases with at least one matching tag.
        """
        from datetime import datetime

        filtered = cases
        if tags:
            tag_set = set(tags)
            filtered = [c for c in cases if tag_set & set(c.tags)]

        log.info("Running eval suite: %d cases (filtered from %d)", len(filtered), len(cases))

        results = []
        for case in filtered:
            result = self.run_case(case)
            results.append(result)

        report = EvalReport(
            results=results,
            timestamp=datetime.now().isoformat(),
        )

        # Save report to disk
        report_path = EVAL_DIR / f"eval_{report.timestamp.replace(':', '-')}.json"
        report_data = {
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
                for r in results
            ],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        log.info("Eval report saved: %s", report_path)

        return report


# ── Predefined Eval Cases ────────────────────────────────────────────────
# These can be imported and used for regression testing.

SMOKE_EVALS = [
    EvalCase(
        name="list_files",
        task="List all files in the current directory",
        expected_tools=["list_directory"],
        max_tool_calls=3,
        max_cost_usd=0.10,
        tags=["smoke", "filesystem"],
    ),
    EvalCase(
        name="read_and_summarize",
        task="Read the file README.md and summarize its contents in 2-3 sentences",
        expected_tools=["read_file"],
        expected_outputs=["Forge"],
        max_tool_calls=5,
        max_cost_usd=0.20,
        tags=["smoke", "filesystem"],
    ),
    EvalCase(
        name="search_code",
        task="Find all Python files that import 'logging' in the forge directory",
        expected_tools=["grep_files"],
        max_tool_calls=5,
        max_cost_usd=0.20,
        tags=["smoke", "search"],
    ),
    EvalCase(
        name="write_and_verify",
        task="Create a file called /tmp/forge_eval_test.txt with the content 'eval test passed' and then read it back to verify",
        expected_tools=["write_file", "read_file"],
        expected_outputs=["eval test passed"],
        max_tool_calls=5,
        max_cost_usd=0.20,
        tags=["smoke", "filesystem"],
    ),
]
