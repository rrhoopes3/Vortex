"""Simple JSON-based persistence for tasks and conversations."""
from __future__ import annotations
import json
import logging
from forge.config import TASKS_FILE, CONVERSATIONS_DIR
from forge.models import TaskResult

log = logging.getLogger("forge.memory")


def save_task(result: TaskResult):
    """Append a completed task result to the tasks file."""
    tasks = load_tasks()
    tasks.append(result.model_dump())
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, default=str), encoding="utf-8")
    log.info("Saved task %s", result.task_id)


def load_tasks() -> list[dict]:
    """Load all saved tasks."""
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []


def get_recent_tasks(limit: int = 20) -> list[dict]:
    """Return the most recent tasks."""
    tasks = load_tasks()
    return tasks[-limit:]


def save_conversation(task_id: str, messages: list[dict]):
    """Save the full conversation log for a task."""
    path = CONVERSATIONS_DIR / f"{task_id}.json"
    path.write_text(json.dumps(messages, indent=2, default=str), encoding="utf-8")
