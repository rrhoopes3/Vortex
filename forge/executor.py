"""
Single-agent executor with client-side tool-calling loop.

Uses grok-4.20-experimental-beta-0304-reasoning with custom tools
(filesystem, shell, browser) to execute plan steps.
"""
from __future__ import annotations
import json
import logging
from typing import Generator
from xai_sdk import Client
from xai_sdk.chat import user, tool_result
from xai_sdk.tools import get_tool_call_type

from forge.config import EXECUTOR_MODEL, EXECUTOR_MAX_ITERATIONS
from forge.tools.registry import ToolRegistry

log = logging.getLogger("forge.executor")

EXECUTOR_SYSTEM = """You are The Forge Executor — an autonomous agent that completes tasks by using tools.

You have access to tools for reading/writing files, running shell commands, and browsing the web.
Work step by step. Use tools to gather information, then act on it. Be precise and efficient.

Rules:
- Always use absolute paths for file operations.
- Check results after each tool call before proceeding.
- If a tool fails, try an alternative approach.
- When the step is complete, summarize what you did and the outcome."""


def execute_step(
    client: Client,
    registry: ToolRegistry,
    step_title: str,
    step_description: str,
    context: str = "",
    sandbox_path: str = "",
) -> Generator[dict, None, str]:
    """
    Execute a single plan step using the reasoning model + client-side tools.

    Yields SSE-style dicts: {"type": "...", ...}
    Returns the final text output.
    """
    chat = client.chat.create(
        model=EXECUTOR_MODEL,
        tools=registry.get_definitions(),
        use_encrypted_content=True,
    )

    prompt = f"{EXECUTOR_SYSTEM}\n\n"
    if sandbox_path:
        prompt += f"SANDBOX MODE ACTIVE: All file operations are restricted to {sandbox_path}. Do not attempt to access paths outside this directory.\n\n"
    if context:
        prompt += f"Context from previous steps:\n{context}\n\n"
    prompt += f"Execute this step:\nTitle: {step_title}\nDescription: {step_description}\n\nUse your tools to complete this. Begin."

    chat.append(user(prompt))

    full_output = ""

    for iteration in range(EXECUTOR_MAX_ITERATIONS):
        log.info("Executor iteration %d for step: %s", iteration + 1, step_title)

        # Stream the response
        collected_content = ""
        tool_calls = []
        response = None

        for response, chunk in chat.stream():
            if chunk.content:
                collected_content += chunk.content
                yield {"type": "content", "content": chunk.content}

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
        yield {"type": "status", "content": f"Hit max iterations ({EXECUTOR_MAX_ITERATIONS}) for step: {step_title}"}

    return full_output
