"""
Multi-agent planner using 16 Grok agents for research and strategy.

Uses grok-4.20-multi-agent-experimental-beta-0304 with server-side tools
(web_search, x_search, code_execution) to research and plan.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Generator
from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search, x_search, code_execution

from forge.config import PLANNER_MODEL, PLANNER_AGENT_COUNT, EXECUTOR_MODEL
from forge.models import PlanStep, ExecutionPlan

log = logging.getLogger("forge.planner")

PLANNER_SYSTEM = """You are The Forge Planner — a 16-agent research council that analyzes tasks and creates execution plans.

Your job:
1. Research the task using web search, X search, and code execution as needed.
2. Break it down into concrete, actionable steps that an executor agent can perform.
3. Output a structured plan.

The executor agent has these tools available:
- read_file(path) — read a file
- write_file(path, content) — write a file
- list_directory(path) — list directory contents
- delete_file(path) — delete a file
- run_command(command) — run a shell command
- browser_navigate(url) — open a URL in a headless browser
- browser_screenshot(filename) — take a screenshot of the current page
- browser_click(selector) — click an element by CSS selector
- browser_type(selector, text) — type text into an input field
- browser_extract_text(selector) — extract visible text from a page/element
- browser_info() — get current page URL, title, and element counts

Format your plan EXACTLY as follows (this will be parsed):

PLAN_START
STEP 1: [title]
[description of what to do]
TOOLS: [comma-separated tool names needed]

STEP 2: [title]
[description of what to do]
TOOLS: [comma-separated tool names needed]

... (as many steps as needed)

SUCCESS: [how to verify the task is complete]
PLAN_END

Be specific in descriptions. Include exact file paths, commands, and expected outcomes."""


def plan(client: Client, task: str, agent_count: int = 16) -> Generator[dict, None, tuple[str, list[PlanStep]]]:
    """
    Use multi-agent model to research and plan a task.

    Yields SSE-style dicts.
    Returns (raw_plan_text, parsed_steps).
    """
    count = max(4, min(16, agent_count))
    chat = client.chat.create(
        model=PLANNER_MODEL,
        agent_count=count,
        tools=[web_search(), x_search(), code_execution()],
        include=["verbose_streaming"],
    )

    chat.append(user(PLANNER_SYSTEM))
    chat.append(user(f"Task: {task}"))

    yield {"type": "status", "phase": "planning", "content": f"{count} agents researching: {task[:100]}..."}

    full_response = ""
    is_thinking = True

    for response, chunk in chat.stream():
        if is_thinking:
            r_tokens = 0
            if hasattr(response, "usage") and response.usage:
                if hasattr(response.usage, "reasoning_tokens") and response.usage.reasoning_tokens:
                    r_tokens = response.usage.reasoning_tokens
            if r_tokens:
                yield {"type": "status", "phase": "planning", "content": f"Deliberating... ({r_tokens:,} reasoning tokens)"}

        if chunk.content and is_thinking:
            is_thinking = False
            yield {"type": "status", "phase": "planning", "content": "Council responding..."}

        if chunk.content:
            full_response += chunk.content
            yield {"type": "plan_content", "content": chunk.content}

    # Parse the structured plan
    steps = parse_plan(full_response)
    yield {"type": "status", "phase": "planning", "content": f"Plan ready: {len(steps)} steps"}

    return full_response, steps


def parse_plan(plan_text: str) -> list[PlanStep]:
    """Parse the structured plan text into PlanStep objects."""
    steps = []

    # Try to extract between PLAN_START and PLAN_END
    match = re.search(r"PLAN_START\s*(.*?)\s*PLAN_END", plan_text, re.DOTALL)
    text = match.group(1) if match else plan_text

    # Split on STEP N: pattern
    step_blocks = re.split(r"STEP\s+(\d+)\s*:\s*", text)

    # step_blocks = ['preamble', '1', 'content...', '2', 'content...', ...]
    i = 1
    while i < len(step_blocks) - 1:
        try:
            step_num = int(step_blocks[i])
        except ValueError:
            i += 2
            continue
        content = step_blocks[i + 1].strip()

        # Extract title (first line) and description
        lines = content.split("\n")
        title = lines[0].strip()
        description_lines = []
        tools_needed = []

        for line in lines[1:]:
            stripped = line.strip()
            if stripped.upper().startswith("TOOLS:"):
                tools_str = stripped[6:].strip()
                tools_needed = [t.strip() for t in tools_str.split(",") if t.strip()]
            elif stripped.upper().startswith("SUCCESS:"):
                pass  # skip success criteria within steps
            else:
                description_lines.append(stripped)

        steps.append(PlanStep(
            step_number=step_num,
            title=title,
            description="\n".join(description_lines).strip(),
            tools_needed=tools_needed,
        ))
        i += 2

    # Fallback: if parsing found nothing, create a single catch-all step
    if not steps:
        log.warning("Could not parse structured plan, creating single step")
        steps = [PlanStep(
            step_number=1,
            title="Execute task",
            description=plan_text[:2000],
            tools_needed=["run_command", "read_file", "write_file"],
        )]

    return steps
