"""
Core orchestrator — wires the planner and executor together.

Flow: User Task → Plan (16 agents) → Parse Steps → Execute Each Step (single agent + tools) → Result
"""
from __future__ import annotations
import logging
import uuid
from typing import Generator
from xai_sdk import Client

from forge.config import XAI_API_KEY
from forge.models import PlanStep, StepResult, TaskResult
from forge.tools import create_registry
from forge import planner, executor

log = logging.getLogger("forge.orchestrator")


class Orchestrator:
    def __init__(self, sandbox_path: str = ""):
        self.client = Client(api_key=XAI_API_KEY)
        self.registry = create_registry()
        self.sandbox_path = sandbox_path
        log.info("Forge initialized. Tools: %s | Sandbox: %s", self.registry.list_tools(), sandbox_path or "OFF")

    def run(self, task: str) -> Generator[dict, None, TaskResult]:
        """
        Run a full task through the plan → execute pipeline.

        Yields SSE-style dicts for real-time UI updates.
        Returns the final TaskResult.
        """
        task_id = str(uuid.uuid4())[:8]
        yield {"type": "status", "content": f"Forge task {task_id} started"}

        # ── Phase 1: Plan ───────────────────────────────────────────────
        yield {"type": "status", "phase": "planning", "content": "Launching 16-agent planner..."}

        plan_raw = ""
        steps: list[PlanStep] = []

        gen = planner.plan(self.client, task)
        try:
            while True:
                msg = next(gen)
                yield msg
        except StopIteration as e:
            if e.value:
                plan_raw, steps = e.value

        if not steps:
            yield {"type": "error", "content": "Planner returned no steps"}
            return TaskResult(task_id=task_id, task=task, plan_raw=plan_raw)

        yield {"type": "status", "phase": "executing", "content": f"Executing {len(steps)} steps..."}

        # ── Phase 2: Execute ────────────────────────────────────────────
        results: list[StepResult] = []
        context_so_far = ""

        for step in steps:
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
                client=self.client,
                registry=self.registry,
                step_title=step.title,
                step_description=step.description,
                context=context_so_far,
                sandbox_path=self.sandbox_path,
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
            except StopIteration as e:
                if e.value:
                    step_output = e.value

            result = StepResult(
                step_number=step.step_number,
                status="failed" if error else "success",
                output=step_output[:2000],
                tools_used=list(set(tools_used)),
                error=error,
            )
            results.append(result)
            context_so_far += f"\nStep {step.step_number} ({step.title}): {step_output[:500]}\n"

            yield {
                "type": "step_done",
                "step": step.step_number,
                "status": result.status,
            }

        # ── Summary ─────────────────────────────────────────────────────
        summary = f"Completed {sum(1 for r in results if r.status == 'success')}/{len(results)} steps"
        yield {"type": "done", "summary": summary}

        return TaskResult(
            task_id=task_id,
            task=task,
            plan_raw=plan_raw,
            results=results,
            final_summary=summary,
        )
