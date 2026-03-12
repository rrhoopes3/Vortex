"""
Agent Kernel — LLM Resource Scheduler.

Cross-pollinated from "AgentOS: From Application Silos to a
Natural Language-Driven Data Ecosystem" (arXiv:2603.08938, Mar 2026).

The AgentOS paper argues that just as a traditional OS kernel multiplexes
CPU time across processes, an Agent Kernel must schedule limited LLM
resources — context windows, token budgets, and API rate limits — across
concurrent agent threads to prevent out-of-memory failures and maintain
system throughput.

This module implements three scheduling capabilities:

  1. TokenBudget       — per-task and global token accounting with quotas
  2. ContextAllocator  — manages context window allocation per step
  3. RateLimiter       — sliding-window rate limiting per provider

These are wired into the orchestrator and executor to enforce resource
governance at the kernel level, replacing the previous ad-hoc cost limits
with a structured scheduling approach.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from forge.config import COST_LIMIT_PER_TASK, COST_LIMIT_PER_SESSION

log = logging.getLogger("forge.kernel")


# ── Token Budget ────────────────────────────────────────────────────────────
# Paper §3.2: "The Agent Kernel allocates limited LLM resources—including
# context windows, token budgets, and API rate limits—across multiple
# concurrent agent threads."

# Default context window sizes by provider (tokens)
CONTEXT_WINDOWS = {
    "xai": 131_072,        # Grok 4.20: 128K
    "anthropic": 200_000,  # Claude: 200K
    "openai": 128_000,     # GPT-4o: 128K
    "lmstudio": 32_768,    # local models: typically 32K
}

# Reserve this fraction of context window for output generation
OUTPUT_RESERVE_FRACTION = 0.25


@dataclass
class TokenAccount:
    """Token usage accounting for a single task or session."""
    input_tokens: int = 0
    output_tokens: int = 0
    budget_input: int = 0    # 0 = unlimited
    budget_output: int = 0   # 0 = unlimited

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def input_remaining(self) -> int:
        if self.budget_input == 0:
            return float("inf")
        return max(0, self.budget_input - self.input_tokens)

    @property
    def output_remaining(self) -> int:
        if self.budget_output == 0:
            return float("inf")
        return max(0, self.budget_output - self.output_tokens)

    @property
    def exhausted(self) -> bool:
        if self.budget_input > 0 and self.input_tokens >= self.budget_input:
            return True
        if self.budget_output > 0 and self.output_tokens >= self.budget_output:
            return True
        return False

    def record(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


class TokenBudgetScheduler:
    """Manages token budgets across concurrent tasks.

    Analogous to an OS memory allocator: each task gets a quota,
    and the scheduler prevents any single task from consuming
    the entire session budget.
    """

    def __init__(
        self,
        session_input_budget: int = 0,
        session_output_budget: int = 0,
    ):
        self._lock = threading.Lock()
        self._session = TokenAccount(
            budget_input=session_input_budget,
            budget_output=session_output_budget,
        )
        self._tasks: dict[str, TokenAccount] = {}

    def allocate_task(
        self,
        task_id: str,
        input_budget: int = 0,
        output_budget: int = 0,
    ) -> TokenAccount:
        """Allocate a token budget for a new task."""
        with self._lock:
            account = TokenAccount(
                budget_input=input_budget,
                budget_output=output_budget,
            )
            self._tasks[task_id] = account
            log.info(
                "Token budget allocated: task=%s input=%s output=%s",
                task_id,
                input_budget or "unlimited",
                output_budget or "unlimited",
            )
            return account

    def record_usage(self, task_id: str, input_tokens: int = 0, output_tokens: int = 0):
        """Record token usage for a task (also updates session totals)."""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].record(input_tokens, output_tokens)
            self._session.record(input_tokens, output_tokens)

    def check_budget(self, task_id: str) -> BudgetVerdict:
        """Check if a task has exceeded its budget or the session budget."""
        with self._lock:
            task_account = self._tasks.get(task_id)

            task_exhausted = task_account.exhausted if task_account else False
            session_exhausted = self._session.exhausted

            if task_exhausted:
                reason = "Task token budget exhausted"
            elif session_exhausted:
                reason = "Session token budget exhausted"
            else:
                reason = ""

            return BudgetVerdict(
                allowed=not (task_exhausted or session_exhausted),
                reason=reason,
                task_tokens=task_account.total_tokens if task_account else 0,
                session_tokens=self._session.total_tokens,
            )

    def get_task_usage(self, task_id: str) -> TokenAccount | None:
        """Get usage stats for a specific task."""
        return self._tasks.get(task_id)

    @property
    def session_usage(self) -> TokenAccount:
        """Get session-level usage stats."""
        return self._session


@dataclass
class BudgetVerdict:
    """Result of a budget check."""
    allowed: bool
    reason: str = ""
    task_tokens: int = 0
    session_tokens: int = 0


# ── Context Allocator ───────────────────────────────────────────────────────
# Paper §3.2: "allocating context windows... across multiple concurrent
# agent threads, preventing out-of-memory failures"


class ContextAllocator:
    """Manages context window allocation across steps.

    Given a model's context window size, allocates budget per step
    to prevent any single step from consuming the entire window.
    Reserves a portion for output generation.
    """

    def __init__(self, provider: str = "xai"):
        self._window_size = CONTEXT_WINDOWS.get(provider, 128_000)
        self._output_reserve = int(self._window_size * OUTPUT_RESERVE_FRACTION)
        self._input_budget = self._window_size - self._output_reserve

    @property
    def total_window(self) -> int:
        return self._window_size

    @property
    def input_budget(self) -> int:
        return self._input_budget

    @property
    def output_reserve(self) -> int:
        return self._output_reserve

    def budget_per_step(self, total_steps: int) -> int:
        """Calculate the token budget per step.

        Distributes the input budget across steps, with a minimum
        of 4K tokens per step to ensure usability.
        """
        if total_steps <= 0:
            return self._input_budget
        per_step = self._input_budget // total_steps
        return max(per_step, 4096)  # minimum 4K per step

    def should_compact(self, current_tokens: int) -> bool:
        """Whether context should be compacted to free space.

        Triggers compaction when usage exceeds 75% of input budget.
        """
        return current_tokens > int(self._input_budget * 0.75)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate from text length.

        Uses the common ~4 chars per token heuristic.
        """
        return len(text) // 4


# ── Rate Limiter ────────────────────────────────────────────────────────────
# Paper §3.2: "API rate limits — across multiple concurrent agent threads"

# Default rate limits (requests per minute) per provider
DEFAULT_RATE_LIMITS = {
    "xai": 60,
    "anthropic": 50,
    "openai": 60,
    "lmstudio": 300,  # local = effectively unlimited
}


class RateLimiter:
    """Sliding-window rate limiter per provider.

    Prevents exceeding API rate limits when multiple tasks or
    steps are running concurrently against the same provider.
    """

    def __init__(self, limits: dict[str, int] | None = None):
        self._limits = limits or DEFAULT_RATE_LIMITS
        self._lock = threading.Lock()
        self._windows: dict[str, list[float]] = {}

    def acquire(self, provider: str) -> RateLimitVerdict:
        """Check if a request is allowed under the rate limit.

        Returns a verdict indicating whether to proceed or wait.
        Automatically cleans up old timestamps.
        """
        limit = self._limits.get(provider, 60)
        now = time.time()
        window_start = now - 60.0  # 1-minute window

        with self._lock:
            if provider not in self._windows:
                self._windows[provider] = []

            # Clean old entries
            self._windows[provider] = [
                t for t in self._windows[provider] if t > window_start
            ]

            current_count = len(self._windows[provider])

            if current_count < limit:
                self._windows[provider].append(now)
                return RateLimitVerdict(allowed=True, wait_seconds=0.0)

            # Calculate how long to wait until the oldest request expires
            oldest = self._windows[provider][0]
            wait = (oldest + 60.0) - now
            return RateLimitVerdict(
                allowed=False,
                wait_seconds=max(0.0, wait),
                reason=f"Rate limit for {provider}: {current_count}/{limit} requests/min",
            )

    def record(self, provider: str):
        """Record a request (if not using acquire)."""
        with self._lock:
            if provider not in self._windows:
                self._windows[provider] = []
            self._windows[provider].append(time.time())

    def get_usage(self, provider: str) -> dict:
        """Get current rate usage for a provider."""
        now = time.time()
        window_start = now - 60.0
        with self._lock:
            timestamps = self._windows.get(provider, [])
            active = [t for t in timestamps if t > window_start]
            limit = self._limits.get(provider, 60)
            return {
                "provider": provider,
                "requests_in_window": len(active),
                "limit": limit,
                "utilization_pct": round(len(active) / limit * 100, 1) if limit else 0,
            }


@dataclass
class RateLimitVerdict:
    """Result of a rate limit check."""
    allowed: bool
    wait_seconds: float = 0.0
    reason: str = ""


# ── Kernel (unified interface) ──────────────────────────────────────────────

class AgentKernel:
    """Unified resource scheduler — the Forge's Agent Kernel.

    Combines token budgeting, context allocation, and rate limiting
    into a single interface that the orchestrator uses for resource
    governance across all tasks.
    """

    def __init__(
        self,
        session_input_budget: int = 0,
        session_output_budget: int = 0,
        rate_limits: dict[str, int] | None = None,
    ):
        self.tokens = TokenBudgetScheduler(
            session_input_budget=session_input_budget,
            session_output_budget=session_output_budget,
        )
        self.rate_limiter = RateLimiter(limits=rate_limits)
        self._allocators: dict[str, ContextAllocator] = {}
        log.info("Agent Kernel initialized")

    def get_allocator(self, provider: str) -> ContextAllocator:
        """Get or create a ContextAllocator for a provider."""
        if provider not in self._allocators:
            self._allocators[provider] = ContextAllocator(provider)
        return self._allocators[provider]

    def pre_request_check(self, task_id: str, provider: str) -> KernelVerdict:
        """Pre-flight check before making an LLM API request.

        Checks both token budget and rate limits.
        Returns a verdict indicating whether to proceed.
        """
        budget = self.tokens.check_budget(task_id)
        if not budget.allowed:
            return KernelVerdict(
                allowed=False,
                reason=budget.reason,
                wait_seconds=0.0,
            )

        rate = self.rate_limiter.acquire(provider)
        if not rate.allowed:
            return KernelVerdict(
                allowed=False,
                reason=rate.reason,
                wait_seconds=rate.wait_seconds,
            )

        return KernelVerdict(allowed=True)

    def post_request_record(
        self,
        task_id: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Record resource usage after an LLM API request completes."""
        self.tokens.record_usage(task_id, input_tokens, output_tokens)

    def summary(self) -> dict:
        """Produce a kernel resource summary."""
        return {
            "session_tokens": {
                "input": self.tokens.session_usage.input_tokens,
                "output": self.tokens.session_usage.output_tokens,
                "total": self.tokens.session_usage.total_tokens,
            },
            "active_tasks": len(self.tokens._tasks),
        }


@dataclass
class KernelVerdict:
    """Result of a kernel pre-request check."""
    allowed: bool
    reason: str = ""
    wait_seconds: float = 0.0
