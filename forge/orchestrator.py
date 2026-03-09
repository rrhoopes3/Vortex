"""
Core orchestrator — wires the planner and executor together.

Flow: User Task → Plan (multi-agent) → Parse Steps → Execute Each Step (single agent + tools) → Result
Direct Mode: User Task → Execute directly (single agent + tools) → Result
"""
from __future__ import annotations
import logging
import threading
import uuid
from typing import Generator

from forge.config import XAI_API_KEY
from forge.models import PlanStep, StepResult, TaskResult
from forge.tools import create_registry
from forge.providers import detect_provider
from forge import planner, executor

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
    ):
        self._client = None  # xAI Client created lazily — only when needed
        self.registry = create_registry()
        self.sandbox_path = sandbox_path
        self.direct_mode = direct_mode
        self.agent_count = max(4, min(16, agent_count))  # clamp 4-16
        self.cancel_event = cancel_event or threading.Event()
        self.executor_model = executor_model  # empty string = use default from config
        self.task_id = task_id  # use caller-provided ID if given
        log.info("Forge initialized. Tools: %s | Sandbox: %s | Direct: %s | Agents: %d | Model: %s",
                 self.registry.list_tools(), sandbox_path or "OFF", direct_mode, self.agent_count,
                 executor_model or "default")

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
        yield {"type": "status", "phase": "executing", "content": "Direct mode — executing with tools..."}

        step_output = ""
        tools_used = []
        error = None

        # Only create xAI client if the executor model needs it
        xai_client = self.client if self._needs_xai_client() else None

        gen = executor.execute_step(
            client=xai_client,
            registry=self.registry,
            step_title="Direct execution",
            step_description=task,
            context="",
            sandbox_path=self.sandbox_path,
            cancel_event=self.cancel_event,
            model=self.executor_model,
        )

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
        result = StepResult(
            step_number=1,
            status=status,
            output=step_output[:2000],
            tools_used=list(set(tools_used)),
            error=error,
        )

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
        """Full pipeline: multi-agent planner → executor."""
        # ── Phase 1: Plan (always xAI — multi-agent Pantheon) ────────────
        yield {"type": "status", "phase": "planning",
               "content": f"Launching {self.agent_count}-agent planner..."}

        plan_raw = ""
        steps: list[PlanStep] = []

        gen = planner.plan(self.client, task, agent_count=self.agent_count, cancel_event=self.cancel_event)
        try:
            while True:
                msg = next(gen)
                yield msg
                if msg.get("type") == "cancelled":
                    yield {"type": "done", "summary": "Task cancelled"}
                    return TaskResult(task_id=task_id, task=task, plan_raw=plan_raw, final_summary="Task cancelled")
        except StopIteration as e:
            if e.value:
                plan_raw, steps = e.value

        if not steps:
            yield {"type": "error", "content": "Planner returned no steps"}
            return TaskResult(task_id=task_id, task=task, plan_raw=plan_raw)

        yield {"type": "status", "phase": "executing", "content": f"Executing {len(steps)} steps..."}

        # ── Phase 2: Execute ────────────────────────────────────────────
        # Only create xAI client for executor if the model needs it
        xai_client = self.client if self._needs_xai_client() else None

        results: list[StepResult] = []
        context_so_far = ""

        for step in steps:
            # Check cancellation before each step
            if self.cancel_event.is_set():
                yield {"type": "cancelled", "content": f"Task cancelled before step {step.step_number}"}
                break

            yield {
                "type": "step_start",
                "step": step.step_number,
                "title": step.title,
                "description": step.description,
            }

            step_output = ""
            tools_used = []
            error = None

            gen = executor.execute_step(
                client=xai_client,
                registry=self.registry,
                step_title=step.title,
                step_description=step.description,
                context=context_so_far,
                sandbox_path=self.sandbox_path,
                cancel_event=self.cancel_event,
                model=self.executor_model,
            )

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
            result = StepResult(
                step_number=step.step_number,
                status=status,
                output=step_output[:2000],
                tools_used=list(set(tools_used)),
                error=error,
            )
            results.append(result)
            context_so_far += f"\nStep {step.step_number} ({step.title}): {step_output[:2000]}\n"

            yield {
                "type": "step_done",
                "step": step.step_number,
                "status": result.status,
            }

            if cancelled:
                break

        # ── Summary ─────────────────────────────────────────────────────
        if self.cancel_event.is_set():
            summary = f"Cancelled after {len(results)}/{len(steps)} steps"
        else:
            summary = f"Completed {sum(1 for r in results if r.status == 'success')}/{len(results)} steps"
        yield {"type": "done", "summary": summary}

        return TaskResult(
            task_id=task_id,
            task=task,
            plan_raw=plan_raw,
            results=results,
            final_summary=summary,
        )
