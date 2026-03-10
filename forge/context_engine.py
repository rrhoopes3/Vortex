"""
Context Engine — adaptive context management inspired by OpenDev paper.

Three capabilities:
  1. Context Compaction  — progressively summarize old step outputs to prevent bloat
  2. Session Memory      — accumulate project knowledge across tasks
  3. Auto Model Routing  — select model based on task complexity
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from forge.config import DATA_DIR

log = logging.getLogger("forge.context_engine")

# ── Context Compaction ────────────────────────────────────────────────────

# When context exceeds this character count, older steps get compacted
COMPACT_THRESHOLD = 6000
# Keep this many recent steps at full detail
KEEP_RECENT_STEPS = 2


def compact_context(context_so_far: str, current_step: int) -> str:
    """Progressively compact older step outputs to prevent context bloat.

    Keeps the most recent KEEP_RECENT_STEPS at full detail.
    Older steps are compressed to a single-line summary.
    """
    if len(context_so_far) < COMPACT_THRESHOLD:
        return context_so_far

    # Parse individual step blocks from context
    # Format: "\nStep N (title): output\n"
    step_pattern = re.compile(
        r"\nStep\s+(\d+)\s+\(([^)]+)\):\s*(.*?)(?=\nStep\s+\d+\s+\(|$)",
        re.DOTALL,
    )
    steps = list(step_pattern.finditer(context_so_far))

    if len(steps) <= KEEP_RECENT_STEPS:
        return context_so_far

    compacted_parts = []
    cutoff = len(steps) - KEEP_RECENT_STEPS

    for i, match in enumerate(steps):
        step_num = match.group(1)
        title = match.group(2)
        output = match.group(3).strip()

        if i < cutoff:
            # Compact: keep first 150 chars as summary
            summary = output[:150].replace("\n", " ").strip()
            if len(output) > 150:
                summary += "..."
            compacted_parts.append(f"\nStep {step_num} ({title}): [COMPACTED] {summary}\n")
        else:
            # Keep recent steps at full detail
            compacted_parts.append(f"\nStep {step_num} ({title}): {output}\n")

    result = "".join(compacted_parts)
    saved = len(context_so_far) - len(result)
    if saved > 0:
        log.info("Context compacted: saved %d chars (%d steps compacted)", saved, cutoff)
    return result


# ── Session Memory ────────────────────────────────────────────────────────

MEMORY_FILE = DATA_DIR / "session_memory.json"
MAX_MEMORIES = 50  # cap total stored memories


def _load_memories() -> list[dict]:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []


def _save_memories(memories: list[dict]):
    # Keep only the most recent MAX_MEMORIES
    trimmed = memories[-MAX_MEMORIES:]
    MEMORY_FILE.write_text(json.dumps(trimmed, indent=2, default=str), encoding="utf-8")


def remember_task(task: str, tools_used: list[str], key_paths: list[str], outcome: str):
    """Store a learning from a completed task.

    Extracts and stores:
    - What the task was about (first 200 chars)
    - Which tools were effective
    - Key file paths discovered
    - Outcome summary
    """
    memories = _load_memories()

    memory = {
        "task": task[:200],
        "tools_effective": list(set(tools_used))[:10],
        "key_paths": key_paths[:10],
        "outcome": outcome[:300],
    }

    # Don't store duplicates (same task substring)
    task_prefix = task[:80].lower()
    memories = [m for m in memories if m.get("task", "")[:80].lower() != task_prefix]
    memories.append(memory)

    _save_memories(memories)
    log.info("Session memory updated: %d total memories", len(memories))


def recall_relevant(task: str, limit: int = 5) -> str:
    """Retrieve session memories relevant to a new task.

    Returns a formatted string to inject into the planner/executor prompt.
    Uses simple keyword overlap scoring.
    """
    memories = _load_memories()
    if not memories:
        return ""

    # Score each memory by keyword overlap with current task
    task_words = set(re.findall(r"\w+", task.lower()))

    scored = []
    for mem in memories:
        mem_words = set(re.findall(r"\w+", mem.get("task", "").lower()))
        mem_words.update(re.findall(r"\w+", " ".join(mem.get("key_paths", [])).lower()))
        overlap = len(task_words & mem_words)
        if overlap > 0:
            scored.append((overlap, mem))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    lines = ["[SESSION MEMORY — learnings from previous tasks]"]
    for _, mem in top:
        tools = ", ".join(mem.get("tools_effective", []))
        paths = ", ".join(mem.get("key_paths", []))
        lines.append(
            f"- Task: {mem['task']}\n"
            f"  Tools: {tools}\n"
            f"  Paths: {paths}\n"
            f"  Outcome: {mem.get('outcome', 'N/A')}"
        )
    lines.append("[END SESSION MEMORY]\n")
    return "\n".join(lines)


def extract_key_paths(step_outputs: list[str]) -> list[str]:
    """Extract file paths mentioned in step outputs for session memory."""
    paths = set()
    # Match common path patterns (Unix and Windows)
    path_pattern = re.compile(r'[A-Za-z]:[/\\][\w./\\-]+|/[\w./\\-]{3,}')
    for output in step_outputs:
        for match in path_pattern.findall(output):
            # Filter out very short or common noise
            if len(match) > 5 and not match.endswith(("/", "\\")):
                paths.add(match)
    return list(paths)[:15]


# ── Auto Model Routing ────────────────────────────────────────────────────

# Task complexity signals
_COMPLEX_SIGNALS = [
    r"\b(refactor|architect|redesign|migrate|optimize|overhaul)\b",
    r"\b(implement|build|create)\b.*\b(system|framework|pipeline|api|server|service)\b",
    r"\b(debug|investigate|diagnose)\b.*\b(complex|intermittent|race condition)\b",
    r"\bmulti[- ]?(file|step|component|module)\b",
    r"\b(security|vulnerability|audit|pentest)\b",
    r"\b(deploy|ci/?cd|infrastructure)\b",
    r"\b(authentication|database|schema|migration)\b",
]

_SIMPLE_SIGNALS = [
    r"\b(fix typo|rename|add comment|update readme|change color)\b",
    r"\b(list|show|display|print|echo|what is)\b",
    r"\b(read|check|look at|open)\b",
    r"\b(simple|quick|small|minor|trivial)\b",
]

# Model tiers
FAST_MODEL = "grok-4-1-fast-reasoning"
POWER_MODEL = "grok-4.20-experimental-beta-0304-reasoning"


def classify_task_complexity(task: str) -> str:
    """Classify a task as 'simple', 'moderate', or 'complex'.

    Used for auto model routing.
    """
    task_lower = task.lower()

    complex_score = sum(1 for pat in _COMPLEX_SIGNALS if re.search(pat, task_lower))
    simple_score = sum(1 for pat in _SIMPLE_SIGNALS if re.search(pat, task_lower))

    # Word count as a proxy for complexity
    word_count = len(task.split())
    if word_count > 50:
        complex_score += 1
    elif word_count < 15:
        simple_score += 1

    if complex_score >= 2:
        return "complex"
    if simple_score >= 2 and complex_score == 0:
        return "simple"
    return "moderate"


def auto_select_model(task: str) -> str:
    """Auto-select the best executor model based on task complexity.

    Returns the model ID string.
    """
    complexity = classify_task_complexity(task)

    if complexity == "simple":
        model = FAST_MODEL
    elif complexity == "complex":
        model = POWER_MODEL
    else:
        # Moderate: use the fast reasoning model (good balance)
        model = FAST_MODEL

    log.info("Auto-routing: task complexity=%s → model=%s", complexity, model)
    return model
