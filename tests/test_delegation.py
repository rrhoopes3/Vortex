"""
Tests for the delegation framework — cross-pollinated from
"Intelligent AI Delegation" (arXiv:2602.11865).

Covers: DelegationContract, TrustLedger, AccountabilityChain,
        DelegationAssessor, AdaptiveRouter, build_step_contract.
"""
import json
import tempfile
import time
from pathlib import Path

import pytest

from forge.delegation import (
    DelegationContract,
    AuthorityBounds,
    TrustLedger,
    TrustEntry,
    AccountabilityChain,
    AccountabilityHop,
    DelegationAssessor,
    AssessmentVerdict,
    PerformanceSignals,
    AdaptiveRouter,
    build_step_contract,
    _infer_verification,
    DEFAULT_TRUST_SCORE,
    TRUST_ALPHA,
    TRUST_REASSIGNMENT_THRESHOLD,
    FALLBACK_CHAINS,
    DEFAULT_FALLBACK_CHAIN,
)


# ── DelegationContract ──────────────────────────────────────────────────────

class TestDelegationContract:
    def test_defaults(self):
        c = DelegationContract()
        assert c.contract_id.startswith("dc_")
        assert c.status == "active"
        assert c.delegator == ""
        assert c.delegatee == ""
        assert c.budget_usd == 0.0
        assert c.verification_criteria == []

    def test_full_contract(self):
        bounds = AuthorityBounds(
            allowed_tools=["read_file", "write_file"],
            sandbox_path="/tmp/sandbox",
            max_iterations=10,
            can_sub_delegate=False,
        )
        c = DelegationContract(
            delegator="orchestrator",
            delegatee="grok-4.20",
            task_summary="Write a test file",
            verification_criteria=["File exists", "File is non-empty"],
            authority_bounds=bounds,
            budget_usd=1.50,
            timeout_seconds=60.0,
        )
        assert c.delegator == "orchestrator"
        assert c.delegatee == "grok-4.20"
        assert len(c.verification_criteria) == 2
        assert c.authority_bounds.max_iterations == 10
        assert not c.authority_bounds.can_sub_delegate

    def test_unique_ids(self):
        ids = {DelegationContract().contract_id for _ in range(100)}
        assert len(ids) == 100


class TestAuthorityBounds:
    def test_defaults(self):
        b = AuthorityBounds()
        assert b.allowed_tools == []
        assert b.sandbox_path == ""
        assert b.max_iterations == 15
        assert not b.can_sub_delegate
        assert b.allowed_providers == []

    def test_custom(self):
        b = AuthorityBounds(
            allowed_tools=["run_command"],
            sandbox_path="/safe",
            can_sub_delegate=True,
            allowed_providers=["xai", "anthropic"],
        )
        assert "run_command" in b.allowed_tools
        assert b.can_sub_delegate
        assert len(b.allowed_providers) == 2


# ── TrustLedger ─────────────────────────────────────────────────────────────

class TestTrustLedger:
    def _tmp_ledger(self, tmp_path):
        return TrustLedger(path=tmp_path / "trust.json")

    def test_default_trust(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        assert tl.get_trust("unknown_model") == DEFAULT_TRUST_SCORE

    def test_record_success_increases_trust(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        initial = tl.get_trust("model_a")
        tl.record_outcome("model_a", success=True)
        assert tl.get_trust("model_a") > initial

    def test_record_failure_decreases_trust(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        initial = tl.get_trust("model_a")
        tl.record_outcome("model_a", success=False)
        assert tl.get_trust("model_a") < initial

    def test_ema_formula(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        tl.record_outcome("model_a", success=True)
        expected = TRUST_ALPHA * 1.0 + (1 - TRUST_ALPHA) * DEFAULT_TRUST_SCORE
        assert abs(tl.get_trust("model_a") - expected) < 0.001

    def test_trust_bounded_0_to_1(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        for _ in range(50):
            tl.record_outcome("model_a", success=False)
        assert tl.get_trust("model_a") >= 0.0

        for _ in range(200):
            tl.record_outcome("model_b", success=True)
        assert tl.get_trust("model_b") <= 1.0

    def test_reassignment_counts_as_failure(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        tl.record_outcome("model_a", success=True, was_reassigned=True)
        # Even though success=True, reassignment → outcome_signal=0.0
        assert tl.get_trust("model_a") < DEFAULT_TRUST_SCORE

    def test_persistence(self, tmp_path):
        tl1 = self._tmp_ledger(tmp_path)
        tl1.record_outcome("model_x", success=True)
        score = tl1.get_trust("model_x")

        tl2 = self._tmp_ledger(tmp_path)
        assert abs(tl2.get_trust("model_x") - score) < 0.001

    def test_get_entry(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        entry = tl.get_entry("model_a")
        assert entry.agent_id == "model_a"
        assert entry.total_delegations == 0

    def test_ranked_agents(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        tl.record_outcome("good_model", success=True)
        tl.record_outcome("bad_model", success=False)
        ranked = tl.ranked_agents(["good_model", "bad_model", "unknown"])
        assert ranked[0][0] == "good_model"

    def test_latency_tracking(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        tl.record_outcome("model_a", success=True, latency_seconds=5.0)
        entry = tl.get_entry("model_a")
        assert entry.avg_latency_seconds > 0

    def test_stats_accumulate(self, tmp_path):
        tl = self._tmp_ledger(tmp_path)
        tl.record_outcome("m", success=True)
        tl.record_outcome("m", success=True)
        tl.record_outcome("m", success=False)
        entry = tl.get_entry("m")
        assert entry.total_delegations == 3
        assert entry.successes == 2
        assert entry.failures == 1


# ── AccountabilityChain ─────────────────────────────────────────────────────

class TestAccountabilityChain:
    def test_create(self):
        chain = AccountabilityChain("task_1", "Do something")
        assert chain.task_id == "task_1"
        assert chain.hops == []

    def test_add_hop(self):
        chain = AccountabilityChain("t1", "task")
        hop = chain.add_hop("orchestrator", "planner", "dc_001")
        assert hop.hop_number == 1
        assert hop.delegator == "orchestrator"
        assert hop.delegatee == "planner"
        assert hop.status == "active"

    def test_complete_hop(self):
        chain = AccountabilityChain("t1", "task")
        chain.add_hop("a", "b", "c1")
        chain.complete_hop(1, output_summary="Done!")
        assert chain.hops[0].status == "completed"
        assert chain.hops[0].output_summary == "Done!"
        assert chain.hops[0].completed_at is not None

    def test_complete_hop_with_error(self):
        chain = AccountabilityChain("t1", "task")
        chain.add_hop("a", "b", "c1")
        chain.complete_hop(1, error="Something broke")
        assert chain.hops[0].status == "failed"
        assert chain.hops[0].error == "Something broke"

    def test_reassign_hop(self):
        chain = AccountabilityChain("t1", "task")
        chain.add_hop("orch", "model_a", "dc_001")
        new_hop = chain.reassign_hop(1, "model_b", "dc_002")
        assert chain.hops[0].status == "reassigned"
        assert new_hop.delegatee == "model_b"
        assert len(chain.hops) == 2

    def test_summary(self):
        chain = AccountabilityChain("t1", "Build a widget")
        chain.add_hop("orch", "planner", "dc_p")
        chain.complete_hop(1, output_summary="3 steps")
        chain.add_hop("orch", "executor", "dc_e1")
        chain.complete_hop(2, error="Failed")

        s = chain.summary()
        assert s["task_id"] == "t1"
        assert s["total_hops"] == 2
        assert s["chain"][0]["status"] == "completed"
        assert s["chain"][1]["status"] == "failed"

    def test_multi_hop_chain(self):
        chain = AccountabilityChain("t1", "Big task")
        for i in range(5):
            chain.add_hop("orch", f"exec_{i}", f"dc_{i}")
            chain.complete_hop(i + 1, output_summary=f"Step {i} done")
        assert len(chain.hops) == 5
        s = chain.summary()
        assert all(h["status"] == "completed" for h in s["chain"])


# ── DelegationAssessor ──────────────────────────────────────────────────────

class TestDelegationAssessor:
    def _make_assessor(self, timeout=0.0):
        contract = DelegationContract(timeout_seconds=timeout)
        return DelegationAssessor(contract)

    def test_healthy_by_default(self):
        a = self._make_assessor()
        verdict = a.assess()
        assert verdict.healthy
        assert not verdict.should_reassign

    def test_observe_content(self):
        a = self._make_assessor()
        a.observe({"type": "content", "content": "Hello world"})
        assert a.signals.content_length == 11

    def test_observe_tool_call(self):
        a = self._make_assessor()
        a.observe({"type": "tool_call", "name": "read_file"})
        assert a.signals.tool_calls == 1

    def test_observe_tool_error(self):
        a = self._make_assessor()
        a.observe({"type": "tool_result", "result": "Error: file not found"})
        assert a.signals.tool_errors == 1

    def test_high_tool_error_rate(self):
        a = self._make_assessor()
        # 3 calls, 2 errors = 66% error rate
        a.observe({"type": "tool_call", "name": "t1"})
        a.observe({"type": "tool_call", "name": "t2"})
        a.observe({"type": "tool_call", "name": "t3"})
        a.observe({"type": "tool_result", "result": "Error: x"})
        a.observe({"type": "tool_result", "result": "Error: y"})
        a.observe({"type": "tool_result", "result": "ok"})

        verdict = a.assess()
        assert not verdict.healthy
        assert verdict.should_reassign
        assert any("error rate" in c.lower() for c in verdict.concerns)

    def test_stall_detection(self):
        a = self._make_assessor()
        # No progress for 3 iterations
        for _ in range(3):
            a.check_iteration()
        verdict = a.assess()
        assert a.signals.stall_detected
        assert verdict.should_reassign

    def test_no_stall_with_progress(self):
        a = self._make_assessor()
        a.observe({"type": "content", "content": "progress"})
        a.check_iteration()
        a.observe({"type": "tool_call", "name": "x"})
        a.check_iteration()
        verdict = a.assess()
        assert verdict.healthy

    def test_timeout_detection(self):
        a = self._make_assessor(timeout=0.01)  # 10ms timeout
        time.sleep(0.02)
        verdict = a.assess()
        assert verdict.should_reassign
        assert any("timeout" in c.lower() for c in verdict.concerns)

    def test_error_messages_collected(self):
        a = self._make_assessor()
        a.observe({"type": "error", "content": "API rate limit"})
        assert len(a.signals.error_messages) == 1

    def test_below_min_tool_calls_no_error_rate_concern(self):
        a = self._make_assessor()
        # Only 1 tool call with error — below MIN_TOOL_CALLS_FOR_ASSESSMENT
        a.observe({"type": "tool_call", "name": "t1"})
        a.observe({"type": "tool_result", "result": "Error"})
        verdict = a.assess()
        assert verdict.healthy  # not enough data to judge


# ── AdaptiveRouter ──────────────────────────────────────────────────────────

class TestAdaptiveRouter:
    def _make_router(self, tmp_path):
        tl = TrustLedger(path=tmp_path / "trust.json")
        return AdaptiveRouter(tl), tl

    def test_selects_primary_when_trusted(self, tmp_path):
        router, tl = self._make_router(tmp_path)
        model = router.select_model("grok-4.20-experimental-beta-0304-reasoning")
        assert model == "grok-4.20-experimental-beta-0304-reasoning"

    def test_reroutes_when_trust_low(self, tmp_path):
        router, tl = self._make_router(tmp_path)
        # Tank the trust of primary model
        for _ in range(30):
            tl.record_outcome("grok-4.20-experimental-beta-0304-reasoning", success=False)
        model = router.select_model("grok-4.20-experimental-beta-0304-reasoning")
        assert model != "grok-4.20-experimental-beta-0304-reasoning"

    def test_fallback_returns_alternative(self, tmp_path):
        router, tl = self._make_router(tmp_path)
        fb = router.get_fallback("grok-4.20-experimental-beta-0304-reasoning")
        assert fb is not None
        assert fb != "grok-4.20-experimental-beta-0304-reasoning"

    def test_fallback_skips_low_trust(self, tmp_path):
        router, tl = self._make_router(tmp_path)
        chain = FALLBACK_CHAINS["grok-4.20-experimental-beta-0304-reasoning"]
        # Tank first fallback
        for _ in range(30):
            tl.record_outcome(chain[0], success=False)
        fb = router.get_fallback("grok-4.20-experimental-beta-0304-reasoning")
        assert fb != chain[0]

    def test_unknown_model_uses_default_chain(self, tmp_path):
        router, tl = self._make_router(tmp_path)
        # Tank the unknown model's trust
        for _ in range(30):
            tl.record_outcome("custom-model-xyz", success=False)
        model = router.select_model("custom-model-xyz")
        assert model in DEFAULT_FALLBACK_CHAIN or model == "custom-model-xyz"


# ── build_step_contract ────────────────────────────────────────────────────

class TestBuildStepContract:
    def test_basic(self):
        c = build_step_contract(
            step_number=1,
            step_title="Read config",
            step_description="Read the config file",
            delegatee_model="grok-4.20",
            tools_needed=["read_file"],
        )
        assert c.delegator == "orchestrator"
        assert c.delegatee == "grok-4.20"
        assert "Step 1" in c.task_summary
        assert c.authority_bounds is not None
        assert "read_file" in c.authority_bounds.allowed_tools

    def test_verification_from_tools(self):
        c = build_step_contract(
            step_number=2,
            step_title="Write output",
            step_description="Write results to file",
            delegatee_model="gpt-4o",
            tools_needed=["write_file"],
        )
        assert any("file" in v.lower() for v in c.verification_criteria)

    def test_verification_from_description(self):
        c = build_step_contract(
            step_number=3,
            step_title="Run tests",
            step_description="Run the test suite",
            delegatee_model="claude-sonnet",
            tools_needed=["run_command"],
        )
        assert any("test" in v.lower() for v in c.verification_criteria)

    def test_budget_and_timeout(self):
        c = build_step_contract(
            step_number=1,
            step_title="Quick step",
            step_description="Do something",
            delegatee_model="grok",
            tools_needed=[],
            budget_usd=2.5,
            timeout_seconds=30.0,
        )
        assert c.budget_usd == 2.5
        assert c.timeout_seconds == 30.0


class TestInferVerification:
    def test_write_file(self):
        v = _infer_verification("create output", ["write_file"])
        assert any("file" in x.lower() for x in v)

    def test_run_command(self):
        v = _infer_verification("run stuff", ["run_command"])
        assert any("exit" in x.lower() or "status" in x.lower() for x in v)

    def test_git(self):
        v = _infer_verification("commit changes", ["git_commit"])
        assert any("git" in x.lower() for x in v)

    def test_http(self):
        v = _infer_verification("fetch data", ["http_get"])
        assert any("http" in x.lower() or "status" in x.lower() for x in v)

    def test_test_keyword(self):
        v = _infer_verification("run the test suite", ["run_command"])
        assert any("test" in x.lower() for x in v)

    def test_build_keyword(self):
        v = _infer_verification("build the project", ["run_command"])
        assert any("build" in x.lower() for x in v)

    def test_deploy_keyword(self):
        v = _infer_verification("deploy to production", [])
        assert any("deploy" in x.lower() for x in v)

    def test_fallback(self):
        v = _infer_verification("do something vague", [])
        assert len(v) >= 1
        assert any("non-empty" in x.lower() or "output" in x.lower() for x in v)


# ── Integration: Models updated with delegation fields ───────────────────

class TestDelegationModels:
    def test_plan_step_has_contract_fields(self):
        from forge.models import PlanStep
        step = PlanStep(
            step_number=1, title="Test", description="Test step",
            contract_id="dc_abc123",
            verification_criteria=["Output exists"],
        )
        assert step.contract_id == "dc_abc123"
        assert len(step.verification_criteria) == 1

    def test_step_result_has_delegation_fields(self):
        from forge.models import StepResult
        r = StepResult(
            step_number=1, status="success",
            contract_id="dc_xyz",
            delegatee_model="grok-4.20",
            was_reassigned=True,
            reassigned_from="gpt-4o",
            trust_score_after=0.75,
            latency_seconds=3.5,
        )
        assert r.was_reassigned
        assert r.reassigned_from == "gpt-4o"
        assert r.trust_score_after == 0.75

    def test_task_result_has_accountability_chain(self):
        from forge.models import TaskResult
        chain_data = {
            "task_id": "t1",
            "original_task": "test",
            "total_hops": 2,
            "chain": [],
        }
        tr = TaskResult(
            task_id="t1", task="test",
            accountability_chain=chain_data,
        )
        assert tr.accountability_chain["total_hops"] == 2

    def test_backward_compat_no_delegation_fields(self):
        """Ensure models still work without delegation fields (backward compat)."""
        from forge.models import PlanStep, StepResult, TaskResult
        step = PlanStep(step_number=1, title="T", description="D")
        assert step.contract_id == ""

        r = StepResult(step_number=1, status="success")
        assert r.delegatee_model == ""
        assert not r.was_reassigned

        tr = TaskResult(task_id="x", task="y")
        assert tr.accountability_chain is None


# ── Context Engine: Trust-aware routing ──────────────────────────────────

class TestTrustAwareRouting:
    def test_auto_select_without_trust(self):
        from forge.context_engine import auto_select_model
        model = auto_select_model("fix a typo in readme")
        assert model  # returns some model

    def test_auto_select_with_trust_override(self, tmp_path):
        from forge.context_engine import auto_select_model, FAST_MODEL, POWER_MODEL
        tl = TrustLedger(path=tmp_path / "trust.json")
        # Tank the fast model's trust
        for _ in range(30):
            tl.record_outcome(FAST_MODEL, success=False)

        model = auto_select_model("fix a typo", trust_ledger=tl)
        # Should have switched away from the tanked model
        assert model == POWER_MODEL

    def test_auto_select_no_override_when_trusted(self, tmp_path):
        from forge.context_engine import auto_select_model, FAST_MODEL
        tl = TrustLedger(path=tmp_path / "trust.json")
        model = auto_select_model("fix a typo", trust_ledger=tl)
        assert model == FAST_MODEL  # default trust is above threshold
