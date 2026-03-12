"""
Core orchestrator — wires the planner and executor together.

Flow: User Task → Plan (multi-agent) → Parse Steps → Execute Each Step (single agent + tools) → Result
Direct Mode: User Task → Execute directly (single agent + tools) → Result

Enhanced with OpenDev-inspired context engineering:
  - Lazy tool discovery (only inject tools needed per step)
  - Adaptive context compaction (summarize old step outputs)
  - Session memory (learn from previous tasks)
  - Instruction reminders (prevent goal drift)
  - Auto model routing (select model by task complexity)

Cross-pollinated with "Intelligent AI Delegation" (arXiv:2602.11865):
  - Delegation contracts (formal specs per step with verification criteria)
  - Trust calibration (EMA-based trust scoring across delegation outcomes)
  - Accountability chains (transitive custody tracking across hops)
  - Adaptive reassignment (fallback to alternate models on failure)
  - Dynamic assessment (real-time delegatee performance monitoring)
"""
from __future__ import annotations
import logging
import threading
import time
import uuid
from typing import Generator

from forge.config import XAI_API_KEY, COST_LIMIT_PER_TASK
from forge.models import PlanStep, StepResult, TaskResult
from forge.tools import create_registry
from forge.tools.registry import resolve_tools_for_step
from forge.providers import detect_provider
from forge.context_engine import (
    compact_context, recall_relevant, remember_task,
    extract_key_paths, auto_select_model,
)
from forge.delegation import (
    TrustLedger, AccountabilityChain, AdaptiveRouter,
    DelegationAssessor, build_step_contract,
)
from forge import planner, executor
from forge.config import TOLL_ENABLED, TOLL_DB_PATH

log = logging.getLogger("forge.orchestrator")


class Orchestrator:
    def __init__(
        self,
        sandbox_path: str = "",
        direct_mode: bool = False,
        agent_count: int = 16,
        cancel_event: threading.Event | None = None,
        executor_model: str = "",
        task_id: str = "",
        toll_sender: str = "",
    ):
        self._client = None  # xAI Client created lazily — only when needed
        self._toll_sender = toll_sender  # external agent ID for billing
        self._toll_relay = None
        if TOLL_ENABLED:
            from forge.toll import TollRelay, Ledger, RateEngine
            ledger = Ledger(TOLL_DB_PATH)
            self._toll_relay = TollRelay(ledger, RateEngine())
            log.info("Toll relay enabled")
        self.registry = create_registry()
        self.sandbox_path = sandbox_path
        self.direct_mode = direct_mode
        self.agent_count = max(4, min(16, agent_count))  # clamp 4-16
        self.cancel_event = cancel_event or threading.Event()
        self.executor_model = executor_model  # empty string = use default from config
        self.task_id = task_id  # use caller-provided ID if given

        # ── Delegation framework (arXiv:2602.11865) ──────────────────────
        self._trust = TrustLedger()
        self._router = AdaptiveRouter(self._trust)

        log.info("Forge initialized. Tools: %s | Sandbox: %s | Direct: %s | Agents: %d | Model: %s",
                 self.registry.list_tools(), sandbox_path or "OFF", direct_mode, self.agent_count,
                 executor_model or "default")

    def _resolve_model(self, task: str) -> str:
        """Resolve the executor model — supports 'auto' routing."""
        if self.executor_model == "auto":
            model = auto_select_model(task)
            log.info("Auto-routed to model: %s", model)
            return model
        return self.executor_model

    @property
    def client(self):
        """Lazy xAI Client — only created when actually needed (xAI model selected)."""
        if self._client is None:
            from xai_sdk import Client
            self._client = Client(api_key=XAI_API_KEY)
        return self._client

    def _needs_xai_client(self, model: str = "") -> bool:
        """Check if the given model (or default executor model) requires the xAI client."""
        from forge.config import EXECUTOR_MODEL
        effective_model = model or self.executor_model or EXECUTOR_MODEL
        return detect_provider(effective_model) == "xai"

    def run(self, task: str) -> Generator[dict, None, TaskResult]:
        """
        Run a full task through the plan → execute pipeline (or direct mode).

        Yields SSE-style dicts for real-time UI updates.
        Returns the final TaskResult.
        """
        task_id = self.task_id or str(uuid.uuid4())[:8]
        yield {"type": "status", "content": f"Forge task {task_id} started"}

        if self.direct_mode:
            return (yield from self._run_direct(task_id, task))
        else:
            return (yield from self._run_planned(task_id, task))

    def _run_direct(self, task_id: str, task: str) -> Generator[dict, None, TaskResult]:
        """Skip planner — send task straight to executor as a single step."""
        resolved_model = self._resolve_model(task)

        # Trust-aware routing: check if primary model should be swapped
        routed_model = self._router.select_model(resolved_model) if resolved_model else resolved_model

        # Session memory: recall relevant learnings
        memory_context = recall_relevant(task)
        context = memory_context if memory_context else ""

        if routed_model != resolved_model:
            yield {"type": "status", "phase": "executing",
                   "content": f"Direct mode — trust-routed from {resolved_model} to {routed_model}"}
        elif resolved_model != self.executor_model and self.executor_model == "auto":
            yield {"type": "status", "phase": "executing",
                   "content": f"Direct mode — auto-routed to {routed_model}"}
        else:
            yield {"type": "status", "phase": "executing", "content": "Direct mode — executing with tools..."}

        effective_model = routed_model or resolved_model
        step_start = time.time()
        step_output = ""
        tools_used = []
        error = None

        # Only create xAI client if the executor model needs it
        xai_client = self.client if self._needs_xai_client(effective_model) else None

        gen = executor.execute_step(
            client=xai_client,
            registry=self.registry,
            step_title="Direct execution",
            step_description=task,
            context=context,
            sandbox_path=self.sandbox_path,
            cancel_event=self.cancel_event,
            model=effective_model,
            task_goal=task,
        )
        if self._toll_relay:
            gen = self._toll_relay.meter(gen, sender=self._toll_sender or "orchestrator",
                                        receiver="executor_direct", session_id=task_id)

        try:
            while True:
                msg = next(gen)
                yield msg
                if msg.get("type") == "content":
                    step_output += msg["content"]
                elif msg.get("type") == "tool_call":
                    tools_used.append(msg["name"])
                elif msg.get("type") == "error":
                    error = msg["content"]
                elif msg.get("type") == "cancelled":
                    error = "Cancelled"
                    break
        except StopIteration as e:
            if e.value:
                step_output = e.value

        cancelled = self.cancel_event.is_set()
        status = "cancelled" if cancelled else ("failed" if error else "success")
        latency = time.time() - step_start

        # Record trust outcome
        if effective_model:
            self._trust.record_outcome(
                effective_model,
                success=(status == "success"),
                latency_seconds=latency,
            )

        result = StepResult(
            step_number=1,
            status=status,
            output=step_output[:2000],
            tools_used=list(set(tools_used)),
            error=error,
            delegatee_model=effective_model,
            trust_score_after=self._trust.get_trust(effective_model) if effective_model else None,
            latency_seconds=round(latency, 2),
        )

        # Session memory: remember what we learned
        if status == "success":
            key_paths = extract_key_paths([step_output])
            remember_task(task, tools_used, key_paths, step_output[:300])

        summary = "Task cancelled" if cancelled else ("Direct execution complete" if not error else "Direct execution failed")
        yield {"type": "done", "summary": summary}

        return TaskResult(
            task_id=task_id,
            task=task,
            plan_raw="(direct mode — no plan)",
            results=[result],
            final_summary=summary,
        )

    def _run_planned(self, task_id: str, task: str) -> Generator[dict, None, TaskResult]:
        """Full pipeline: multi-agent planner → executor.

        Enhanced with:
        - Session memory injection into planner context
        - Lazy tool discovery per step (only inject tools the planner says are needed)
        - Adaptive context compaction (summarize older steps as context grows)
        - Instruction reminders (pass task goal to executor for drift prevention)
        - Auto model routing (resolve model before execution)

        Cross-pollinated (arXiv:2602.11865):
        - Delegation contracts per step with verification criteria
        - Accountability chain tracking across all hops
        - Dynamic assessment with real-time performance signals
        - Adaptive reassignment: failed steps retried on fallback models
        - Trust calibration updated per step outcome
        """
        resolved_model = self._resolve_model(task)

        # ── Accountability Chain (paper §3.3) ────────────────────────────
        chain = AccountabilityChain(task_id, task)

        # ── Phase 1: Plan (always xAI — multi-agent Pantheon) ────────────
        # Inject session memory into the planner's task context
        memory_hint = recall_relevant(task)
        enriched_task = task
        if memory_hint:
            enriched_task = f"{task}\n\n{memory_hint}"
            log.info("Injected session memory into planner (%d chars)", len(memory_hint))

        if resolved_model != self.executor_model and self.executor_model == "auto":
            yield {"type": "status", "phase": "planning",
                   "content": f"Auto-routed executor to {resolved_model}. Launching {self.agent_count}-agent planner..."}
        else:
            yield {"type": "status", "phase": "planning",
                   "content": f"Launching {self.agent_count}-agent planner..."}

        # Record planner delegation in accountability chain
        planner_hop = chain.add_hop("orchestrator", "planner", "planner_delegation")

        plan_raw = ""
        steps: list[PlanStep] = []

        gen = planner.plan(self.client, enriched_task, agent_count=self.agent_count, cancel_event=self.cancel_event)
        if self._toll_relay:
            gen = self._toll_relay.meter(gen, sender=self._toll_sender or "orchestrator",
                                        receiver="planner", session_id=task_id)
        try:
            while True:
                msg = next(gen)
                yield msg
                if msg.get("type") == "cancelled":
                    chain.complete_hop(planner_hop.hop_number, error="Cancelled")
                    yield {"type": "done", "summary": "Task cancelled"}
                    return TaskResult(task_id=task_id, task=task, plan_raw=plan_raw,
                                     final_summary="Task cancelled",
                                     accountability_chain=chain.summary())
        except StopIteration as e:
            if e.value:
                plan_raw, steps = e.value

        if not steps:
            chain.complete_hop(planner_hop.hop_number, error="No steps returned")
            yield {"type": "error", "content": "Planner returned no steps"}
            return TaskResult(task_id=task_id, task=task, plan_raw=plan_raw,
                              accountability_chain=chain.summary())

        chain.complete_hop(planner_hop.hop_number, output_summary=f"{len(steps)} steps planned")

        yield {"type": "status", "phase": "executing", "content": f"Executing {len(steps)} steps..."}

        # ── Phase 2: Execute ────────────────────────────────────────────
        results: list[StepResult] = []
        context_so_far = ""
        all_tools_used = []
        all_step_outputs = []

        for step in steps:
            # Check cancellation before each step
            if self.cancel_event.is_set():
                yield {"type": "cancelled", "content": f"Task cancelled before step {step.step_number}"}
                break

            # ── Trust-Aware Model Selection (paper §4.2) ──────────────
            step_model = self._router.select_model(resolved_model) if resolved_model else resolved_model

            # ── Delegation Contract (paper §3.1) ─────────────────────
            contract = build_step_contract(
                step_number=step.step_number,
                step_title=step.title,
                step_description=step.description,
                delegatee_model=step_model or resolved_model,
                tools_needed=step.tools_needed,
                sandbox_path=self.sandbox_path,
                budget_usd=COST_LIMIT_PER_TASK / max(len(steps), 1),
                timeout_seconds=120.0,
            )
            step.contract_id = contract.contract_id
            step.verification_criteria = contract.verification_criteria

            # ── Accountability Hop ─────────────────────────────────────
            step_hop = chain.add_hop("orchestrator", step_model or "executor", contract.contract_id)

            # ── Lazy Tool Discovery ──────────────────────────────────────
            tool_filter = None
            if step.tools_needed:
                tool_filter = resolve_tools_for_step(step.tools_needed)
                log.info("Step %d: lazy discovery → %d tools (from %s)",
                         step.step_number, len(tool_filter), step.tools_needed)

            yield {
                "type": "step_start",
                "step": step.step_number,
                "title": step.title,
                "description": step.description,
                "tools_filtered": len(tool_filter) if tool_filter else len(self.registry.list_tools()),
                "contract_id": contract.contract_id,
                "delegatee": step_model or "default",
                "verification_criteria": contract.verification_criteria,
            }

            # ── Execute with Dynamic Assessment (paper §4.1) ──────────
            result = yield from self._execute_step_with_assessment(
                task_id=task_id,
                step=step,
                step_model=step_model or resolved_model,
                contract=contract,
                resolved_model=resolved_model,
                context_so_far=context_so_far,
                tool_filter=tool_filter,
                task_goal=task,
            )

            # ── Accountability tracking ─────────────────────────────────
            chain.complete_hop(
                step_hop.hop_number,
                output_summary=result.output[:200],
                error=result.error or "",
            )

            results.append(result)
            all_tools_used.extend(result.tools_used)
            all_step_outputs.append(result.output)
            context_so_far += f"\nStep {step.step_number} ({step.title}): {result.output}\n"

            yield {
                "type": "step_done",
                "step": step.step_number,
                "status": result.status,
                "delegatee": result.delegatee_model,
                "was_reassigned": result.was_reassigned,
                "trust_score": result.trust_score_after,
                "latency_s": result.latency_seconds,
            }

            if self.cancel_event.is_set():
                break

        # ── Summary ─────────────────────────────────────────────────────
        if self.cancel_event.is_set():
            summary = f"Cancelled after {len(results)}/{len(steps)} steps"
        else:
            success_count = sum(1 for r in results if r.status == "success")
            reassigned_count = sum(1 for r in results if r.was_reassigned)
            summary = f"Completed {success_count}/{len(results)} steps"
            if reassigned_count > 0:
                summary += f" ({reassigned_count} reassigned)"

            # Session memory: remember what we learned from successful tasks
            if success_count > 0:
                key_paths = extract_key_paths(all_step_outputs)
                outcome = "; ".join(
                    f"Step {r.step_number}: {r.status}" for r in results
                )
                remember_task(task, all_tools_used, key_paths, outcome)

        yield {"type": "done", "summary": summary, "accountability_chain": chain.summary()}

        return TaskResult(
            task_id=task_id,
            task=task,
            plan_raw=plan_raw,
            results=results,
            final_summary=summary,
            accountability_chain=chain.summary(),
        )

    def _execute_step_with_assessment(
        self,
        task_id: str,
        step: PlanStep,
        step_model: str,
        contract,
        resolved_model: str,
        context_so_far: str,
        tool_filter: set[str] | None,
        task_goal: str,
    ) -> Generator[dict, None, StepResult]:
        """Execute a step with dynamic assessment and adaptive reassignment.

        If the primary model fails or underperforms, attempts reassignment
        to a fallback model from the trust-ranked chain.
        """
        effective_model = step_model
        was_reassigned = False
        reassigned_from = ""
        max_attempts = 2  # primary + one fallback

        for attempt in range(max_attempts):
            step_start = time.time()

            # ── Adaptive Context Compaction ───────────────────────────────
            compacted_context = compact_context(context_so_far, step.step_number)

            # ── Dynamic Assessor (paper §4.1) ────────────────────────────
            assessor = DelegationAssessor(contract)

            xai_client = self.client if self._needs_xai_client(effective_model) else None

            gen = executor.execute_step(
                client=xai_client,
                registry=self.registry,
                step_title=step.title,
                step_description=step.description,
                context=compacted_context,
                sandbox_path=self.sandbox_path,
                cancel_event=self.cancel_event,
                model=effective_model,
                tool_filter=tool_filter,
                task_goal=task_goal,
            )
            if self._toll_relay:
                gen = self._toll_relay.meter(
                    gen, sender=self._toll_sender or "planner",
                    receiver=f"executor_step_{step.step_number}",
                    session_id=task_id,
                )

            step_output = ""
            tools_used = []
            error = None

            try:
                while True:
                    msg = next(gen)

                    # Feed message to assessor for real-time monitoring
                    assessor.observe(msg)

                    yield msg
                    if msg.get("type") == "content":
                        step_output += msg["content"]
                    elif msg.get("type") == "tool_call":
                        tools_used.append(msg["name"])
                    elif msg.get("type") == "error":
                        error = msg["content"]
                    elif msg.get("type") == "cancelled":
                        error = "Cancelled"
                        break
            except StopIteration as e:
                if e.value:
                    step_output = e.value

            latency = time.time() - step_start
            cancelled = self.cancel_event.is_set()
            status = "cancelled" if cancelled else ("failed" if error else "success")

            # ── Trust Update ─────────────────────────────────────────────
            self._trust.record_outcome(
                effective_model,
                success=(status == "success"),
                latency_seconds=latency,
                was_reassigned=was_reassigned,
            )

            # ── Adaptive Reassignment (paper §4.3) ───────────────────────
            # If step failed and this is the first attempt, try a fallback
            if status == "failed" and attempt == 0 and not cancelled:
                fallback = self._router.get_fallback(effective_model)
                if fallback:
                    yield {
                        "type": "status",
                        "phase": "reassigning",
                        "content": f"Step {step.step_number} failed on {effective_model}, "
                                   f"reassigning to {fallback}...",
                    }
                    reassigned_from = effective_model
                    effective_model = fallback
                    was_reassigned = True
                    continue  # retry with fallback model

            # Step completed (success, final failure, or cancelled)
            return StepResult(
                step_number=step.step_number,
                status=status,
                output=step_output[:2000],
                tools_used=list(set(tools_used)),
                error=error,
                contract_id=contract.contract_id,
                delegatee_model=effective_model,
                was_reassigned=was_reassigned,
                reassigned_from=reassigned_from,
                trust_score_after=self._trust.get_trust(effective_model),
                latency_seconds=round(latency, 2),
            )

        # Should not reach here, but safety net
        return StepResult(
            step_number=step.step_number,
            status="failed",
            error="Exhausted all delegation attempts",
            delegatee_model=effective_model,
            was_reassigned=was_reassigned,
            reassigned_from=reassigned_from,
        )
