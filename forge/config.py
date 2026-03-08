import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── API ─────────────────────────────────────────────────────────────────────
XAI_API_KEY = os.getenv("XAI_API_KEY")

# ── Models ──────────────────────────────────────────────────────────────────
PLANNER_MODEL = "grok-4.20-multi-agent-experimental-beta-0304"
EXECUTOR_MODEL = "grok-4.20-experimental-beta-0304-reasoning"
PLANNER_AGENT_COUNT = 16

# Available executor models (id → display label)
EXECUTOR_MODELS = {
    "grok-4.20-experimental-beta-0304-reasoning": "Grok 4.20 Reasoning  ($2/$6)",
    "grok-4-1-fast-reasoning":                    "Grok 4.1 Fast Reasoning  ($0.20/$0.50)",
    "grok-4-1-fast-non-reasoning":                "Grok 4.1 Fast  ($0.20/$0.50)",
    "grok-code-fast-1":                           "Grok Code Fast  ($0.20/$1.50)",
}

# ── Paths ───────────────────────────────────────────────────────────────────
FORGE_DIR = Path(__file__).resolve().parent
DATA_DIR = FORGE_DIR / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"

# Ensure data dirs exist
DATA_DIR.mkdir(exist_ok=True)
CONVERSATIONS_DIR.mkdir(exist_ok=True)

# ── Limits ──────────────────────────────────────────────────────────────────
EXECUTOR_MAX_ITERATIONS = 10
SHELL_TIMEOUT_SECONDS = 30
SHELL_WORKING_DIR = Path("B:/Grok")  # restrict shell commands to this tree
