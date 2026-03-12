"""
Tests for the Agent Kernel — LLM Resource Scheduler.
Cross-pollinated from AgentOS (arXiv:2603.08938).

Covers: TokenBudgetScheduler, ContextAllocator, RateLimiter, AgentKernel.
"""
import time

import pytest

from forge.kernel import (
    TokenAccount,
    TokenBudgetScheduler,
    BudgetVerdict,
    ContextAllocator,
    CONTEXT_WINDOWS,
    OUTPUT_RESERVE_FRACTION,
    RateLimiter,
    RateLimitVerdict,
    AgentKernel,
    KernelVerdict,
)


# ── TokenAccount ───────────────────────────────────────────────────────────

class TestTokenAccount:
    def test_defaults(self):
        a = TokenAccount()
        assert a.total_tokens == 0
        assert not a.exhausted

    def test_record(self):
        a = TokenAccount()
        a.record(input_tokens=100, output_tokens=50)
        assert a.input_tokens == 100
        assert a.output_tokens == 50
        assert a.total_tokens == 150

    def test_unlimited_remaining(self):
        a = TokenAccount()
        assert a.input_remaining == float("inf")
        assert a.output_remaining == float("inf")

    def test_budget_remaining(self):
        a = TokenAccount(budget_input=1000, budget_output=500)
        a.record(input_tokens=300)
        assert a.input_remaining == 700
        assert a.output_remaining == 500

    def test_exhausted_input(self):
        a = TokenAccount(budget_input=100)
        a.record(input_tokens=100)
        assert a.exhausted

    def test_exhausted_output(self):
        a = TokenAccount(budget_output=50)
        a.record(output_tokens=60)
        assert a.exhausted

    def test_not_exhausted_unlimited(self):
        a = TokenAccount()
        a.record(input_tokens=999999, output_tokens=999999)
        assert not a.exhausted


# ── TokenBudgetScheduler ───────────────────────────────────────────────────

class TestTokenBudgetScheduler:
    def test_allocate_task(self):
        sched = TokenBudgetScheduler()
        account = sched.allocate_task("t1", input_budget=10000)
        assert account.budget_input == 10000

    def test_record_updates_both(self):
        sched = TokenBudgetScheduler()
        sched.allocate_task("t1")
        sched.record_usage("t1", input_tokens=500, output_tokens=200)
        assert sched.get_task_usage("t1").total_tokens == 700
        assert sched.session_usage.total_tokens == 700

    def test_budget_check_allowed(self):
        sched = TokenBudgetScheduler()
        sched.allocate_task("t1", input_budget=10000)
        verdict = sched.check_budget("t1")
        assert verdict.allowed

    def test_budget_check_task_exhausted(self):
        sched = TokenBudgetScheduler()
        sched.allocate_task("t1", input_budget=100)
        sched.record_usage("t1", input_tokens=150)
        verdict = sched.check_budget("t1")
        assert not verdict.allowed
        assert "Task" in verdict.reason

    def test_budget_check_session_exhausted(self):
        sched = TokenBudgetScheduler(session_input_budget=200)
        sched.allocate_task("t1")
        sched.record_usage("t1", input_tokens=250)
        verdict = sched.check_budget("t1")
        assert not verdict.allowed
        assert "Session" in verdict.reason

    def test_multiple_tasks_share_session(self):
        sched = TokenBudgetScheduler(session_input_budget=1000)
        sched.allocate_task("t1")
        sched.allocate_task("t2")
        sched.record_usage("t1", input_tokens=400)
        sched.record_usage("t2", input_tokens=400)
        assert sched.session_usage.input_tokens == 800
        assert sched.check_budget("t1").allowed
        sched.record_usage("t2", input_tokens=300)
        assert not sched.check_budget("t1").allowed  # session exhausted


# ── ContextAllocator ───────────────────────────────────────────────────────

class TestContextAllocator:
    def test_default_window(self):
        ca = ContextAllocator("xai")
        assert ca.total_window == CONTEXT_WINDOWS["xai"]

    def test_output_reserve(self):
        ca = ContextAllocator("xai")
        assert ca.output_reserve == int(CONTEXT_WINDOWS["xai"] * OUTPUT_RESERVE_FRACTION)
        assert ca.input_budget + ca.output_reserve == ca.total_window

    def test_budget_per_step(self):
        ca = ContextAllocator("xai")
        per_step = ca.budget_per_step(5)
        assert per_step == ca.input_budget // 5

    def test_budget_per_step_minimum(self):
        ca = ContextAllocator("xai")
        per_step = ca.budget_per_step(1000)  # very many steps
        assert per_step >= 4096

    def test_budget_per_step_zero_steps(self):
        ca = ContextAllocator("xai")
        assert ca.budget_per_step(0) == ca.input_budget

    def test_should_compact(self):
        ca = ContextAllocator("xai")
        assert not ca.should_compact(1000)
        threshold = int(ca.input_budget * 0.75)
        assert ca.should_compact(threshold + 1)

    def test_estimate_tokens(self):
        ca = ContextAllocator()
        assert ca.estimate_tokens("Hello world!") == 3  # 12 chars / 4

    def test_unknown_provider(self):
        ca = ContextAllocator("unknown_provider")
        assert ca.total_window == 128_000  # fallback


# ── RateLimiter ────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allowed_by_default(self):
        rl = RateLimiter()
        verdict = rl.acquire("xai")
        assert verdict.allowed
        assert verdict.wait_seconds == 0.0

    def test_rate_limit_exceeded(self):
        rl = RateLimiter(limits={"test": 3})
        rl.acquire("test")
        rl.acquire("test")
        rl.acquire("test")
        verdict = rl.acquire("test")
        assert not verdict.allowed
        assert verdict.wait_seconds > 0

    def test_different_providers_independent(self):
        rl = RateLimiter(limits={"a": 1, "b": 1})
        rl.acquire("a")
        verdict_a = rl.acquire("a")
        verdict_b = rl.acquire("b")
        assert not verdict_a.allowed
        assert verdict_b.allowed

    def test_record(self):
        rl = RateLimiter(limits={"test": 2})
        rl.record("test")
        rl.record("test")
        verdict = rl.acquire("test")
        assert not verdict.allowed

    def test_get_usage(self):
        rl = RateLimiter(limits={"xai": 60})
        rl.acquire("xai")
        usage = rl.get_usage("xai")
        assert usage["requests_in_window"] == 1
        assert usage["limit"] == 60
        assert usage["utilization_pct"] > 0


# ── AgentKernel ────────────────────────────────────────────────────────────

class TestAgentKernel:
    def test_create(self):
        k = AgentKernel()
        assert k.tokens is not None
        assert k.rate_limiter is not None

    def test_pre_request_allowed(self):
        k = AgentKernel()
        k.tokens.allocate_task("t1")
        verdict = k.pre_request_check("t1", "xai")
        assert verdict.allowed

    def test_pre_request_budget_blocked(self):
        k = AgentKernel(session_input_budget=100)
        k.tokens.allocate_task("t1")
        k.tokens.record_usage("t1", input_tokens=150)
        verdict = k.pre_request_check("t1", "xai")
        assert not verdict.allowed

    def test_pre_request_rate_blocked(self):
        k = AgentKernel(rate_limits={"test": 1})
        k.tokens.allocate_task("t1")
        k.pre_request_check("t1", "test")
        verdict = k.pre_request_check("t1", "test")
        assert not verdict.allowed
        assert verdict.wait_seconds > 0

    def test_post_request_record(self):
        k = AgentKernel()
        k.tokens.allocate_task("t1")
        k.post_request_record("t1", "xai", input_tokens=500, output_tokens=100)
        assert k.tokens.session_usage.total_tokens == 600

    def test_get_allocator(self):
        k = AgentKernel()
        alloc = k.get_allocator("anthropic")
        assert alloc.total_window == CONTEXT_WINDOWS["anthropic"]

    def test_summary(self):
        k = AgentKernel()
        k.tokens.allocate_task("t1")
        k.post_request_record("t1", "xai", input_tokens=100)
        s = k.summary()
        assert s["session_tokens"]["input"] == 100
        assert s["active_tasks"] == 1
