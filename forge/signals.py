"""
Per-interaction signal extraction — OpenClaw-RL (arXiv:2603.10165).

Extracts fine-grained quality signals from every executor message,
going beyond binary success/fail. Signals feed into TrustLedger and Vault
for continuous trust calibration and hindsight learning.

Also provides user-correction detection (re-submissions, kills, manual edits).
"""
from __future__ import annotations

import logging
import re
import time as _time
from dataclasses import dataclass, field

log = logging.getLogger("forge.signals")

# ── Error detection (shared with DelegationAssessor) ──────────────────────
_ERROR_RE = re.compile(
    r"\b(error|exception|traceback|failed|failure|errno|fatal)\b",
    re.IGNORECASE,
)
_FALSE_POSITIVE_RE = re.compile(
    r"\b(no errors?|without errors?|error.?free|0 errors?)\b",
    re.IGNORECASE,
)


# ── Data structures ───────────────────────────────────────────────────────

@dataclass
class InteractionSignal:
    """Single quality signal from one executor message."""
    signal_type: str   # tool_success, tool_error, content_chunk, token_usage
    value: float       # 0.0 (bad) to 1.0 (good)
    source: str        # tool name, "content", "token_usage"
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class StepSignals:
    """Aggregated quality signals for a completed step."""
    step_number: int = 0
    signals: list[InteractionSignal] = field(default_factory=list)
    tool_success_count: int = 0
    tool_error_count: int = 0
    content_length: int = 0
    latency_seconds: float = 0.0
    cost_usd: float = 0.0
    had_errors: bool = False

    @property
    def tool_error_rate(self) -> float:
        total = self.tool_success_count + self.tool_error_count
        return self.tool_error_count / total if total > 0 else 0.0

    @property
    def aggregate_score(self) -> float:
        """Weighted quality score, 0.0 to 1.0."""
        tool_reliability = 1.0 - self.tool_error_rate
        latency_score = self._score_latency()
        content_score = min(self.content_length / 200.0, 1.0)  # some output is good
        error_free = 0.0 if self.had_errors else 1.0

        return (
            0.4 * tool_reliability
            + 0.3 * latency_score
            + 0.2 * content_score
            + 0.1 * error_free
        )

    def _score_latency(self) -> float:
        """Score latency: 1.0 if under expected, degrades to 0.0 at 3x."""
        if not hasattr(self, "_expected_latency") or self._expected_latency <= 0:
            return 0.7  # neutral default
        ratio = self.latency_seconds / self._expected_latency
        if ratio <= 1.0:
            return 1.0
        if ratio >= 3.0:
            return 0.0
        return 1.0 - (ratio - 1.0) / 2.0


class SignalExtractor:
    """Observes SSE messages during step execution, extracts quality signals.

    Mirrors DelegationAssessor.observe() pattern but outputs scalar signals
    instead of boolean assessments.
    """

    def __init__(self, expected_latency: float = 60.0, step_number: int = 0):
        self._expected_latency = expected_latency
        self._step_number = step_number
        self._signals: list[InteractionSignal] = []
        self._tool_successes = 0
        self._tool_errors = 0
        self._content_length = 0
        self._cost_usd = 0.0
        self._had_errors = False

    def observe(self, msg: dict) -> InteractionSignal | None:
        """Process one SSE message, return signal if extracted."""
        msg_type = msg.get("type", "")
        now = _time.time()

        if msg_type == "tool_result":
            return self._observe_tool_result(msg, now)
        elif msg_type == "content":
            return self._observe_content(msg, now)
        elif msg_type == "token_usage":
            return self._observe_token_usage(msg, now)
        elif msg_type == "error":
            self._had_errors = True
            sig = InteractionSignal(
                signal_type="error", value=0.0,
                source=msg.get("content", "")[:100], timestamp=now,
            )
            self._signals.append(sig)
            return sig
        return None

    def _observe_tool_result(self, msg: dict, now: float) -> InteractionSignal:
        result_text = str(msg.get("result", ""))
        name = msg.get("name", "unknown")

        is_error = bool(_ERROR_RE.search(result_text)) and not bool(
            _FALSE_POSITIVE_RE.search(result_text)
        )

        if is_error:
            self._tool_errors += 1
            sig = InteractionSignal(
                signal_type="tool_error", value=0.0, source=name,
                timestamp=now, metadata={"snippet": result_text[:200]},
            )
        else:
            self._tool_successes += 1
            sig = InteractionSignal(
                signal_type="tool_success", value=1.0, source=name,
                timestamp=now,
            )
        self._signals.append(sig)
        return sig

    def _observe_content(self, msg: dict, now: float) -> InteractionSignal:
        chunk = msg.get("content", "")
        self._content_length += len(chunk)
        sig = InteractionSignal(
            signal_type="content_chunk", value=0.5, source="content",
            timestamp=now, metadata={"cumulative_length": self._content_length},
        )
        self._signals.append(sig)
        return sig

    def _observe_token_usage(self, msg: dict, now: float) -> InteractionSignal:
        cost = msg.get("cost_usd", 0.0)
        self._cost_usd += cost
        sig = InteractionSignal(
            signal_type="token_usage", value=0.5, source="token_usage",
            timestamp=now, metadata={"cost_usd": cost},
        )
        self._signals.append(sig)
        return sig

    def finalize(self, latency_seconds: float) -> StepSignals:
        """Compute aggregate metrics after step completes."""
        signals = StepSignals(
            step_number=self._step_number,
            signals=list(self._signals),
            tool_success_count=self._tool_successes,
            tool_error_count=self._tool_errors,
            content_length=self._content_length,
            latency_seconds=latency_seconds,
            cost_usd=self._cost_usd,
            had_errors=self._had_errors,
        )
        # Attach expected latency for scoring
        signals._expected_latency = self._expected_latency
        return signals


# ── User Correction Detection ─────────────────────────────────────────────

@dataclass
class CorrectionSignal:
    """Signal that the user is dissatisfied with a prior result."""
    signal_type: str   # "resubmission", "kill", "manual_edit"
    severity: float    # 0.0-1.0 (kill=1.0, resubmission=0.7, edit=0.5)
    original_task_id: str = ""
    description: str = ""


class CorrectionDetector:
    """Detects user dissatisfaction signals: re-submissions, kills, file edits."""

    MAX_RECENT = 50

    def __init__(self, similarity_threshold: float = 0.6):
        self._similarity_threshold = similarity_threshold
        self._recent_tasks: list[tuple[str, float, str]] = []  # (task, timestamp, task_id)
        self._killed_tasks: set[str] = set()

    def record_task(self, task: str, task_id: str):
        """Record a submitted task for future similarity checks."""
        self._recent_tasks.append((task, _time.time(), task_id))
        if len(self._recent_tasks) > self.MAX_RECENT:
            self._recent_tasks = self._recent_tasks[-self.MAX_RECENT:]

    def detect_resubmission(self, task: str) -> CorrectionSignal | None:
        """Check if task is semantically similar to a recent one."""
        task_words = self._extract_keywords(task)
        if not task_words:
            return None

        for prev_task, ts, prev_id in reversed(self._recent_tasks):
            prev_words = self._extract_keywords(prev_task)
            if not prev_words:
                continue
            overlap = len(task_words & prev_words) / max(
                len(task_words | prev_words), 1
            )
            if overlap >= self._similarity_threshold:
                log.info(
                    "Re-submission detected (%.0f%% overlap): '%s' ≈ '%s'",
                    overlap * 100, task[:50], prev_task[:50],
                )
                return CorrectionSignal(
                    signal_type="resubmission",
                    severity=0.7,
                    original_task_id=prev_id,
                    description=f"Task resubmitted ({overlap:.0%} similar to {prev_id})",
                )
        return None

    def record_kill(self, task_id: str) -> CorrectionSignal:
        """Record a task kill as a strong negative signal."""
        self._killed_tasks.add(task_id)
        log.info("Kill signal recorded for task %s", task_id)
        return CorrectionSignal(
            signal_type="kill",
            severity=1.0,
            original_task_id=task_id,
            description=f"Task {task_id} killed by user",
        )

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract keywords (3+ chars) for similarity comparison."""
        return {w.lower() for w in re.findall(r"\w+", text) if len(w) >= 3}


# Module-level singleton for app.py / orchestrator to share
correction_detector = CorrectionDetector()
