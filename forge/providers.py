"""
Multi-provider executor adapters for The Forge.

Each provider implements the same generator interface as the xAI executor:
  yields {"type": "content"|"tool_call"|"tool_result"|"status"|"error"|"cancelled", ...}
  returns full_output: str

Supported providers:
  - xai     → native xai_sdk (handled in executor.py)
  - anthropic → Anthropic Messages API
  - openai  → OpenAI Chat Completions API
  - lmstudio → OpenAI-compatible local server
"""
from __future__ import annotations
import json
import logging
import threading
from typing import Generator

from forge.config import ANTHROPIC_API_KEY, OPENAI_API_KEY, LMSTUDIO_BASE_URL
from forge.tools.registry import ToolRegistry

log = logging.getLogger("forge.providers")


# ── Provider Detection ─────────────────────────────────────────────────────

def detect_provider(model: str) -> str:
    """Determine which API provider to use based on model name."""
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    if model.startswith("lmstudio:"):
        return "lmstudio"
    return "xai"


# ── Tool Format Converters ─────────────────────────────────────────────────

def _to_anthropic_tools(registry: ToolRegistry) -> list[dict]:
    """Convert registry tools to Anthropic format."""
    tools = []
    for t in registry.get_raw_tools():
        tools.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        })
    return tools


def _to_openai_tools(registry: ToolRegistry) -> list[dict]:
    """Convert registry tools to OpenAI function-calling format."""
    tools = []
    for t in registry.get_raw_tools():
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        })
    return tools


# ── Anthropic Adapter ──────────────────────────────────────────────────────

def run_anthropic(
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    sandbox_path: str,
    cancel_event: threading.Event | None,
    max_iterations: int,
) -> Generator[dict, None, str]:
    """Run Anthropic Messages API with tool-calling loop."""
    try:
        import anthropic
    except ImportError:
        yield {"type": "error", "content": "anthropic package not installed. Run: pip install anthropic"}
        return ""

    if not ANTHROPIC_API_KEY:
        yield {"type": "error", "content": "ANTHROPIC_API_KEY not set in .env"}
        return ""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    tools = _to_anthropic_tools(registry)

    messages = [{"role": "user", "content": user_prompt}]
    full_output = ""

    for iteration in range(max_iterations):
        if cancel_event and cancel_event.is_set():
            yield {"type": "cancelled", "content": "Step cancelled"}
            return full_output

        log.info("Anthropic iteration %d (model: %s)", iteration + 1, model)

        try:
            # Stream the response
            collected_text = ""
            tool_uses = []

            with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=tools,
                messages=messages,
            ) as stream:
                for event in stream:
                    if cancel_event and cancel_event.is_set():
                        yield {"type": "cancelled", "content": "Step cancelled"}
                        return full_output

                    if hasattr(event, "type"):
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                collected_text += event.delta.text
                                yield {"type": "content", "content": event.delta.text}

                # Get the final message for tool_use blocks
                response = stream.get_final_message()

        except Exception as e:
            log.error("Anthropic stream failed: %s", e)
            yield {"type": "error", "content": f"Anthropic API error: {type(e).__name__}: {e}"}
            return full_output

        full_output += collected_text

        # Check for tool_use blocks
        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if not tool_uses:
            log.info("Anthropic step complete (no tool calls)")
            break

        # Build assistant message with all content blocks
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools and build tool_result message
        tool_results = []
        for tu in tool_uses:
            if cancel_event and cancel_event.is_set():
                yield {"type": "cancelled", "content": "Step cancelled"}
                return full_output

            yield {"type": "tool_call", "name": tu.name, "args": tu.input}
            log.info("Tool call: %s(%s)", tu.name, tu.input)

            result = registry.execute(tu.name, tu.input, sandbox_path=sandbox_path)

            display_result = result[:500] + "..." if len(result) > 500 else result
            yield {"type": "tool_result", "name": tu.name, "result": display_result}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        yield {"type": "status", "content": f"Hit max iterations ({max_iterations})"}

    return full_output


# ── OpenAI Adapter ─────────────────────────────────────────────────────────

def run_openai(
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    sandbox_path: str,
    cancel_event: threading.Event | None,
    max_iterations: int,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Generator[dict, None, str]:
    """Run OpenAI Chat Completions API with tool-calling loop."""
    try:
        from openai import OpenAI
    except ImportError:
        yield {"type": "error", "content": "openai package not installed. Run: pip install openai"}
        return ""

    effective_key = api_key or OPENAI_API_KEY
    if not effective_key and not base_url:
        yield {"type": "error", "content": "OPENAI_API_KEY not set in .env"}
        return ""

    # LM Studio doesn't need a real key but the SDK requires one
    client_kwargs = {}
    if base_url:
        client_kwargs["base_url"] = base_url
        client_kwargs["api_key"] = effective_key or "lm-studio"
    else:
        client_kwargs["api_key"] = effective_key

    client = OpenAI(**client_kwargs)
    tools = _to_openai_tools(registry)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    full_output = ""

    for iteration in range(max_iterations):
        if cancel_event and cancel_event.is_set():
            yield {"type": "cancelled", "content": "Step cancelled"}
            return full_output

        log.info("OpenAI iteration %d (model: %s, base_url: %s)", iteration + 1, model, base_url or "default")

        try:
            # Stream the response
            collected_text = ""
            tool_calls_acc: dict[int, dict] = {}  # index → {id, name, arguments}

            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools if tools else None,
                stream=True,
            )

            for chunk in stream:
                if cancel_event and cancel_event.is_set():
                    yield {"type": "cancelled", "content": "Step cancelled"}
                    return full_output

                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta
                if delta and delta.content:
                    collected_text += delta.content
                    yield {"type": "content", "content": delta.content}

                # Accumulate streamed tool calls
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.id or "",
                                "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                                "arguments": "",
                            }
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

        except Exception as e:
            log.error("OpenAI stream failed: %s", e)
            yield {"type": "error", "content": f"OpenAI API error: {type(e).__name__}: {e}"}
            return full_output

        full_output += collected_text

        # No tool calls → done
        if not tool_calls_acc:
            log.info("OpenAI step complete (no tool calls)")
            break

        # Build assistant message with tool calls
        tool_calls_list = []
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            tool_calls_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })

        assistant_msg = {"role": "assistant", "content": collected_text or None, "tool_calls": tool_calls_list}
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in tool_calls_list:
            if cancel_event and cancel_event.is_set():
                yield {"type": "cancelled", "content": "Step cancelled"}
                return full_output

            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_call", "name": func_name, "args": args}
            log.info("Tool call: %s(%s)", func_name, args)

            result = registry.execute(func_name, args, sandbox_path=sandbox_path)

            display_result = result[:500] + "..." if len(result) > 500 else result
            yield {"type": "tool_result", "name": func_name, "result": display_result}

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
    else:
        yield {"type": "status", "content": f"Hit max iterations ({max_iterations})"}

    return full_output
