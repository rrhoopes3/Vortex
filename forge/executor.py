"""
Single-agent executor with client-side tool-calling loop.

Supports multiple providers:
  - xAI (grok-*): native xai_sdk
  - Anthropic (claude-*): Anthropic Messages API
  - OpenAI (gpt-*, o3-*): OpenAI Chat Completions API
  - LM Studio (lmstudio:*): OpenAI-compatible local server
"""
from __future__ import annotations
import json
import logging
import time
import threading
from typing import Generator
from xai_sdk import Client
from xai_sdk.chat import user, tool_result
from xai_sdk.tools import get_tool_call_type

from forge.config import EXECUTOR_MODEL, EXECUTOR_MAX_ITERATIONS, LMSTUDIO_BASE_URL
from forge.tools.registry import ToolRegistry
from forge.providers import detect_provider, run_anthropic, run_openai, calculate_cost

log = logging.getLogger("forge.executor")

MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # seconds

EXECUTOR_SYSTEM = """You are The Forge Executor — an autonomous agent that completes tasks by using tools.

You have access to tools for reading/writing files, running shell commands, and browsing the web.
Work step by step. Use tools to gather information, then act on it. Be precise and efficient.

Rules:
- Always use absolute paths for file operations.
- Check results after each tool call before proceeding.
- If a tool fails, try an alternative approach.
- IMPORTANT: If context from previous steps already contains the information you need (file contents, grep results, etc.), use that directly — do NOT re-read the same files.
- Minimize tool calls. Combine searches when possible instead of running many small queries.
- Stay focused on files relevant to the current task. Do NOT explore unrelated directories or projects.
- When the step is complete, provide a clear summary of findings and outcome."""


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

    # Build the full prompt (shared across all providers)
    prompt = f"{EXECUTOR_SYSTEM}\n\n"
    if sandbox_path:
        prompt += f"SANDBOX MODE ACTIVE: All file operations are restricted to {sandbox_path}. Do not attempt to access paths outside this directory.\n\n"
    if context:
        prompt += f"Context from previous steps:\n{context}\n\n"
    prompt += f"Execute this step:\nTitle: {step_title}\nDescription: {step_description}\n\nUse your tools to complete this. Begin."

    # ── Route to non-xAI providers ───────────────────────────────────
    if provider == "anthropic":
        return (yield from run_anthropic(
            model=use_model, system_prompt=EXECUTOR_SYSTEM, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            tool_filter=tool_filter, task_goal=task_goal,
        ))
    elif provider == "openai":
        return (yield from run_openai(
            model=use_model, system_prompt=EXECUTOR_SYSTEM, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            tool_filter=tool_filter, task_goal=task_goal,
        ))
    elif provider == "lmstudio":
        # Strip "lmstudio:" prefix; use "default" if nothing after it
        lm_model = use_model.split(":", 1)[1] if ":" in use_model else "default"
        return (yield from run_openai(
            model=lm_model, system_prompt=EXECUTOR_SYSTEM, user_prompt=prompt,
            registry=registry, sandbox_path=sandbox_path,
            cancel_event=cancel_event, max_iterations=iteration_limit,
            base_url=LMSTUDIO_BASE_URL, tool_filter=tool_filter, task_goal=task_goal,
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
                f"[SYSTEM REMINDER] Original task goal: {task_goal[:500]}\n"
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
                    call_type = "client_side_tool"
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

            func_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_call", "name": func_name, "args": args}
            log.info("Tool call: %s(%s)", func_name, args)

            result = registry.execute(func_name, args, sandbox_path=sandbox_path)

            # Truncate large results for display
            display_result = result[:500] + "..." if len(result) > 500 else result
            yield {"type": "tool_result", "name": func_name, "result": display_result}

            chat.append(tool_result(result, tool_call_id=tc.id))
    else:
        yield {"type": "status", "content": f"Hit max iterations ({iteration_limit}) for step: {step_title}"}

    return full_output
