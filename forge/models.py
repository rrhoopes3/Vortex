from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class PlanStep(BaseModel):
    step_number: int
    title: str
    description: str
    tools_needed: list[str] = Field(
        default_factory=list,
        description="Tools likely needed: read_file, write_file, run_command, etc.",
    )
    expected_output: str = ""
    # Delegation metadata (populated by delegation framework)
    contract_id: str = ""
    verification_criteria: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    task_summary: str
    steps: list[PlanStep]
    success_criteria: str = ""


class StepResult(BaseModel):
    step_number: int
    status: Literal["success", "failed", "skipped", "cancelled"] = "success"
    output: str = ""
    tools_used: list[str] = Field(default_factory=list)
    error: str | None = None
    # Delegation metadata
    contract_id: str = ""
    delegatee_model: str = ""
    was_reassigned: bool = False
    reassigned_from: str = ""
    trust_score_after: float | None = None
    latency_seconds: float = 0.0


class TaskResult(BaseModel):
    task_id: str
    task: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    plan: ExecutionPlan | None = None
    plan_raw: str = ""
    results: list[StepResult] = Field(default_factory=list)
    final_summary: str = ""
    # Delegation metadata
    accountability_chain: dict | None = None  # from AccountabilityChain.summary()
