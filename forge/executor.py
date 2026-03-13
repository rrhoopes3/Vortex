"""
Single-agent executor with client-side tool-calling loop.

Supports multiple providers:
  - xAI (grok-*): native xai_sdk
  - Anthropic (claude-*): Anthropic Messages API
  - OpenAI (gpt-*, o3-*): OpenAI Chat Completions API
  - LM Studio (lmstudio:*): OpenAI-compatible local server
  - Ollama (ollama:*): Ollama local server (OpenAI-compatible)
"""
from __future__ import annotations
import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Generator
from xai_sdk import Client
from xai_sdk.chat import user, tool_result
from xai_sdk.tools import get_tool_call_type

from forge.config import EXECUTOR_MODEL, EXECUTOR_MAX_ITERATIONS, LMSTUDIO_BASE_URL, OLLAMA_BASE_URL
from forge.tools.registry import ToolRegistry
from forge.tools.escalation import EscalationError
from forge.guardrails import GuardrailEngine
from forge.providers import detect_provider, run_anthropic, run_openai, calculate_cost

log = logging.getLogger("forge.executor")

MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # seconds


def _current_timestamp() -> str:
    """Return a human-readable timestamp string for injection into prompts."""
    now = datetime.now()
    utc = datetime.now(timezone.utc)
    return (
        f"Current date/time: {now.strftime('%A, %B %d, %Y at %I:%M %p')} (local) / "
        f"{utc.strftime('%Y-%m-%dT%H:%M:%SZ')} (UTC). "
        f"This is the PRESENT — not past, not future."
    )


EXECUTOR_SYSTEM_TEMPLATE = """You are The Forge Executor — an autonomous agent that completes tasks by using tools.

{timestamp}

You have access to tools for reading/writing files, running shell commands, and browsing the web.
Work step by step. Use tools to gather information, then act on it. Be precise and efficient.

Rules:
- Always use absolute paths for file operations.
- Check results after each tool call before proceeding.
- If a tool fails, try an alternative approach.
- IMPORTANT: If context from previous steps already contains the information you need (file contents, grep results, etc.), use that directly — do NOT re-read the same files.
- Minimize tool calls. Combine searches when possible instead of running many small queries.
- Stay focused on files relevant to the current task. Do NOT explore unrelated directories or projects.
- When the step is complete, provide a clear summary of findings and outcome.
- Do NOT pip install packages — project dependencies are pre-installed. Use run_python directly."""


def _build_system_prompt() -> str:
    """Build the executor system prompt with current timestamp."""
    return EXECUTOR_SYSTEM_TEMPLATE.format(timestamp=_current_timestamp())


# Backward compat — static reference for tests that import this
EXECUTOR_SYSTEM = EXECUTOR_SYSTEM_TEMPLATE.format(timestamp="(timestamp injected at runtime)")


def execute_step(
    client: Client | None,
    registry: ToolRegistry,
    step_title: str,
    step_description: str,
    context: str = "",
    sandbox_path: str = "",
    cancel_event: threading.Event | None = None,
    model: str = "",
    max_iterations: int = 0,
    tool_filter: set[str] | None = None,
    task_goal: str = "",
    guardrail_engine: GuardrailEngine | None = None,
) -> Generator[dict, None, str]:
    """
    Execute a single plan step using the reasoning model + client-side tools.

    Yields SSE-style dicts: {"type": "...", ...}
    Returns the final text output.

    Routes to the correct provider based on model name prefix.

    tool_filter: if set, only these tools are made available (lazy discovery).
    task_goal: original task description, used for instruction reminders.
    """
    use_model = model if model else EXECUTOR_MODEL
    iteration_limit = max_iterations if max_iterations > 0 else EXECUTOR_MAX_ITERATIONS
    provider = detect_provider(use_model)
    log.info("Using executor model: %s (provider: %s, max %d iterations, tools: %s)",
             use_model, provider, iteration_limit,
             f"{len(tool_filter)} filtered" if tool_filter else "all")

    # Build the system prompt with live timestamp
    system_prompt = _build_system_prompt()

    # Build the full prompt (shared across all providers)
    prompt = f"{system_prompt}\n\n"
    if sandbox_path:
        prompt += f"SANDBOX MODE ACTIVE: All file operations are restricted to {sandbox_path}. Do not attempt to access paths outside this directory.\n\n"
    if context:
        prompt += f"Context from previous steps:\n{context}\n\n"
    prompt += f"Execute this step:\nTitle: {step_title}\nDescription: {step_description}\n\nUse your tools to complete this. Begin."

    # ── Route to non-xAI providers ───────────────────────────────────
    if provider == "anthropic":
        return (yield from run_anthropic(
            model=use_model, system_prompt=system_prompt, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            tool_filter=tool_filter, task_goal=task_goal,
            guardrail_engine=guardrail_engine,
        ))
    elif provider == "openai":
        return (yield from run_openai(
            model=use_model, system_prompt=system_prompt, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            tool_filter=tool_filter, task_goal=task_goal,
            guardrail_engine=guardrail_engine,
        ))
    elif provider == "lmstudio":
        # Strip "lmstudio:" prefix; use "default" if nothing after it
        lm_model = use_model.split(":", 1)[1] if ":" in use_model else "default"
        return (yield from run_openai(
            model=lm_model, system_prompt=system_prompt, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            base_url=LMSTUDIO_BASE_URL, tool_filter=tool_filter, task_goal=task_goal,
            guardrail_engine=guardrail_engine,
        ))
    elif provider == "ollama":
        # Strip "ollama:" prefix; use "default" if nothing after it
        ollama_model = use_model.split(":", 1)[1] if ":" in use_model else "default"
        return (yield from run_openai(
            model=ollama_model, system_prompt=system_prompt, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            base_url=OLLAMA_BASE_URL, tool_filter=tool_filter, task_goal=task_goal,
            guardrail_engine=guardrail_engine,
        ))

    # ── xAI provider (original path) ────────────────────────────────
    chat = client.chat.create(
        model=use_model,
        tools=registry.get_definitions(only=tool_filter),
        use_encrypted_content=True,
    )

    chat.append(user(prompt))

    full_output = ""

    # Instruction reminder interval — re-inject task goal every N iterations
    REMINDER_INTERVAL = 3

    for iteration in range(iteration_limit):
        # Check cancellation before each iteration
        if cancel_event and cancel_event.is_set():
            yield {"type": "cancelled", "content": "Step cancelled"}
            return full_output

        # ── Instruction Reminder (prevent goal drift) ────────────────
        if task_goal and iteration > 0 and iteration % REMINDER_INTERVAL == 0:
            reminder = (
                f"[SYSTEM REMINDER] {_current_timestamp()}\n"
                f"Original task goal: {task_goal[:500]}\n"
                f"Current step: {step_title}\nStay focused on completing this step."
            )
            chat.append(user(reminder))
            log.info("Injected instruction reminder at iteration %d", iteration + 1)

        log.info("Executor iteration %d for step: %s", iteration + 1, step_title)

        # Stream the response with retry logic
        collected_content = ""
        tool_calls = []
        response = None
        stream_success = False

        for attempt in range(MAX_RETRIES):
            try:
                for response, chunk in chat.stream():
                    # Check cancellation during streaming
                    if cancel_event and cancel_event.is_set():
                        yield {"type": "cancelled", "content": "Step cancelled"}
                        return full_output

                    if chunk.content:
                        collected_content += chunk.content
                        yield {"type": "content", "content": chunk.content}

                stream_success = True
                break  # Stream completed successfully

            except Exception as e:
                if cancel_event and cancel_event.is_set():
                    yield {"type": "cancelled", "content": "Step cancelled"}
                    return full_output

                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    log.warning("Executor stream attempt %d failed: %s — retrying in %ds", attempt + 1, e, delay)
                    yield {"type": "status", "content": f"API error, retrying in {delay}s... ({type(e).__name__})"}
                    time.sleep(delay)
                else:
                    log.error("Executor stream failed after %d attempts: %s", MAX_RETRIES, e)
                    yield {"type": "error", "content": f"API failed after {MAX_RETRIES} attempts: {type(e).__name__}: {e}"}
                    return full_output

        if not stream_success:
            return full_output

        # Emit token usage for cost tracking (xAI responses may include usage)
        if response and hasattr(response, "usage") and response.usage:
            in_tok = getattr(response.usage, "input_tokens", 0) or getattr(response.usage, "prompt_tokens", 0) or 0
            out_tok = getattr(response.usage, "output_tokens", 0) or getattr(response.usage, "completion_tokens", 0) or 0
            if in_tok or out_tok:
                yield calculate_cost(use_model, in_tok, out_tok)

        # Collect tool calls from the final response
        if response and hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                try:
                    call_type = get_tool_call_type(tc)
                except Exception:
                    call_type = "unknown"
                if call_type == "client_side_tool":
                    tool_calls.append(tc)

        full_output += collected_content

        # If no tool calls, execution is complete
        if not tool_calls:
            log.info("Step complete (no more tool calls)")
            break

        # Execute tool calls and feed results back
        chat.append(response)
        for tc in tool_calls:
            # Check cancellation before each tool call
            if cancel_event and cancel_event.is_set():
                yield {"type": "cancelled", "content": "Step cancelled"}
                return full_output

            func = getattr(tc, "function", None)
            if func is None or not getattr(func, "name", None):
                log.warning("Skipping tool call with missing function/name: %s", tc)
                continue
            func_name = func.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # ── Input Guardrails (concurrent, pre-execution) ─────────
            if guardrail_engine:
                violations = guardrail_engine.check_input(func_name, args)
                for v in violations:
                    yield {"type": "guardrail_violation", "guardrail": v.guardrail_name,
                           "severity": v.severity, "message": v.message}
                if guardrail_engine.has_blocking_violation(violations):
                    error_msg = f"Guardrail blocked: {violations[0].message}"
                    chat.append(tool_result(json.dumps({"error": error_msg}), tool_call_id=tc.id))
                    continue

            yield {"type": "tool_call", "name": func_name, "args": args}
            log.info("Tool call: %s(%s)", func_name, args)

            # ── Execute with escalation handling ─────────────────────
            try:
                result = registry.execute(func_name, args, sandbox_path=sandbox_path)
            except EscalationError as esc:
                yield {"type": "escalation", "reason": esc.reason,
                       "category": esc.category, "context": esc.context}
                return full_output

            # ── Generative UI interception ────────────────────────────
            from forge.generative_ui import intercept_widget_result
            widget_event, result = intercept_widget_result(result)
            if widget_event:
                yield widget_event

            # ── Output Guardrails (concurrent, post-execution) ───────
            if guardrail_engine:
                out_violations = guardrail_engine.check_output(result)
                for v in out_violations:
                    yield {"type": "guardrail_violation", "guardrail": v.guardrail_name,
                           "severity": v.severity, "message": v.message}

            # Truncate large results for display
            display_result = result[:500] + "..." if len(result) > 500 else result
            yield {"type": "tool_result", "name": func_name, "result": display_result}

            chat.append(tool_result(result, tool_call_id=tc.id))
    else:
        yield {"type": "status", "content": f"Hit max iterations ({iteration_limit}) for step: {step_title}"}

    return full_output
