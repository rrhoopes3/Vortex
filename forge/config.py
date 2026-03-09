import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── API Keys ───────────────────────────────────────────────────────────────
XAI_API_KEY = os.getenv("XAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

# ── Models ──────────────────────────────────────────────────────────────────
PLANNER_MODEL = "grok-4.20-multi-agent-experimental-beta-0304"
EXECUTOR_MODEL = "grok-4.20-experimental-beta-0304-reasoning"
PLANNER_AGENT_COUNT = 16

# Available executor models (id → display label)
EXECUTOR_MODELS = {
    # xAI
    "grok-4.20-experimental-beta-0304-reasoning": "Grok 4.20 Reasoning ($2/$6)",
    "grok-4-1-fast-reasoning":                    "Grok 4.1 Fast Reasoning ($0.20/$0.50)",
    "grok-4-1-fast-non-reasoning":                "Grok 4.1 Fast ($0.20/$0.50)",
    # Anthropic
    "claude-sonnet-4-20250514":                   "Claude Sonnet 4 ($3/$15)",
    "claude-haiku-4-20250414":                    "Claude Haiku 4 ($0.80/$4)",
    # OpenAI
    "gpt-4o":                                     "GPT-4o ($2.50/$10)",
    "gpt-4o-mini":                                "GPT-4o Mini ($0.15/$0.60)",
    "o3-mini":                                    "o3-mini ($1.10/$4.40)",
    # Local
    "lmstudio:default":                           "LM Studio (Local)",
}

# Arena-only models (same pool)
ARENA_MODELS = EXECUTOR_MODELS

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

# ── Arena ──────────────────────────────────────────────────────────────────
ARENA_MASTER_MODEL = PLANNER_MODEL       # 16-agent Pantheon for commentary/judging
ARENA_DEFAULT_FIGHTER_MODEL = "grok-4-1-fast-reasoning"
ARENA_FIGHTER_AGENT_COUNT = 4
ARENA_RECON_ITERATIONS = 3               # tool iterations for recon round
ARENA_FORGE_ITERATIONS = 5               # tool iterations for weapon forge round
ARENA_COMBAT_TURNS = 6                   # total turns in combat (3 per team)
