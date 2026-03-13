"""
Hindsight-Guided Directives — OpenClaw-RL (arXiv:2603.10165).

When a step fails and gets reassigned to a fallback model that succeeds,
generate contrastive "directive" entries: what went wrong vs. what worked.
These are stored in the Vault's notes_space and injected into future
executor prompts to prevent repeating the same mistakes.
"""
from __future__ import annotations

import logging

from forge.models import PlanStep, StepResult
from forge.vault import NotesEntry, _detect_domains, _short_id

log = logging.getLogger("forge.directives")


def generate_directive(
    failed_result: StepResult,
    success_result: StepResult,
    step: PlanStep,
    task: str,
) -> NotesEntry:
    """Create a contrastive directive from a failed→success reassignment.

    Format: "AVOID: {bad_pattern} | PREFER: {good_pattern} | Context: {desc}"
    """
    # Extract bad pattern from the failure
    bad_parts = []
    if failed_result.error:
        bad_parts.append(f"error: {failed_result.error[:80]}")
    if failed_result.delegatee_model:
        bad_parts.append(f"model: {failed_result.delegatee_model}")
    bad_tools = ", ".join(failed_result.tools_used[:5]) if failed_result.tools_used else "no tools"
    bad_parts.append(f"tools: {bad_tools}")
    bad_pattern = "; ".join(bad_parts)

    # Extract good pattern from the success
    good_parts = []
    if success_result.delegatee_model:
        good_parts.append(f"model: {success_result.delegatee_model}")
    good_tools = ", ".join(success_result.tools_used[:5]) if success_result.tools_used else "no tools"
    good_parts.append(f"tools: {good_tools}")
    if success_result.output:
        good_parts.append(f"approach: {success_result.output[:80]}")
    good_pattern = "; ".join(good_parts)

    context = step.description[:80] if step.description else step.title

    content = f"AVOID: {bad_pattern} | PREFER: {good_pattern} | Context: {context}"

    # Detect domain from task
    domains = _detect_domains(f"{task} {step.description}")
    domain = domains[0] if domains else "general"

    log.info("Directive generated for step %d: %s", step.step_number, content[:100])

    return NotesEntry(
        entry_id=_short_id(),
        topic=f"directive:{domain}:{step.title[:30]}",
        content=content[:300],
        domain=domain,
        pattern_type="directive",
    )


def detect_reassignment_directives(
    results: list[StepResult],
    steps: list[PlanStep],
    task: str,
) -> list[NotesEntry]:
    """Scan results for reassigned steps and generate directives.

    A directive is generated when:
    - A step was reassigned (was_reassigned=True) and succeeded
    - We can reconstruct the failed attempt from the reassigned_from model
    """
    directives: list[NotesEntry] = []

    for result in results:
        if not result.was_reassigned or result.status != "success":
            continue

        # Find the matching step
        step = next((s for s in steps if s.step_number == result.step_number), None)
        if not step:
            continue

        # Construct a synthetic "failed result" from the reassignment info
        failed_result = StepResult(
            step_number=result.step_number,
            status="failed",
            delegatee_model=result.reassigned_from,
            tools_used=[],  # we don't have the failed attempt's tools
            error="Reassigned due to failure or poor performance",
        )

        directive = generate_directive(failed_result, result, step, task)
        directives.append(directive)

    if directives:
        log.info("Generated %d hindsight directives from reassignments", len(directives))

    return directives
