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

# Available executor models with pricing (cost per 1M tokens)
# Format: id → {"label": str, "provider": str, "cost_in": float, "cost_out": float}
EXECUTOR_MODELS = {
    "auto": {
        "label": "Auto (smart routing)", "provider": "auto",
        "cost_in": 0, "cost_out": 0,  # varies by routed model
    },
    # xAI
    "grok-4.20-experimental-beta-0304-reasoning": {
        "label": "Grok 4.20 Reasoning", "provider": "xAI",
        "cost_in": 2.00, "cost_out": 6.00,
    },
    "grok-4-1-fast-reasoning": {
        "label": "Grok 4.1 Fast Reasoning", "provider": "xAI",
        "cost_in": 0.20, "cost_out": 0.50,
    },
    "grok-4-1-fast-non-reasoning": {
        "label": "Grok 4.1 Fast", "provider": "xAI",
        "cost_in": 0.20, "cost_out": 0.50,
    },
    # Anthropic
    "claude-sonnet-4-20250514": {
        "label": "Claude Sonnet 4", "provider": "Anthropic",
        "cost_in": 3.00, "cost_out": 15.00,
    },
    "claude-haiku-4-20250414": {
        "label": "Claude Haiku 4", "provider": "Anthropic",
        "cost_in": 0.80, "cost_out": 4.00,
    },
    # OpenAI
    "gpt-4o": {
        "label": "GPT-4o", "provider": "OpenAI",
        "cost_in": 2.50, "cost_out": 10.00,
    },
    "gpt-4o-mini": {
        "label": "GPT-4o Mini", "provider": "OpenAI",
        "cost_in": 0.15, "cost_out": 0.60,
    },
    "o3-mini": {
        "label": "o3-mini", "provider": "OpenAI",
        "cost_in": 1.10, "cost_out": 4.40,
    },
    # Local
    "lmstudio:default": {
        "label": "LM Studio (Local)", "provider": "Local",
        "cost_in": 0, "cost_out": 0,
    },
}

# Arena-only models (same pool)
ARENA_MODELS = EXECUTOR_MODELS

# ── Cost Limits ───────────────────────────────────────────────────────────
COST_LIMIT_PER_TASK = float(os.getenv("FORGE_COST_LIMIT_TASK", "5.00"))    # USD
COST_LIMIT_PER_SESSION = float(os.getenv("FORGE_COST_LIMIT_SESSION", "50.00"))  # USD

# ── Paths ───────────────────────────────────────────────────────────────────
FORGE_DIR = Path(__file__).resolve().parent
DATA_DIR = FORGE_DIR / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"

# Ensure data dirs exist
DATA_DIR.mkdir(exist_ok=True)
CONVERSATIONS_DIR.mkdir(exist_ok=True)

# ── Limits ──────────────────────────────────────────────────────────────────
EXECUTOR_MAX_ITERATIONS = 15  # raised from 10 — context compaction prevents bloat
SHELL_TIMEOUT_SECONDS = 30
SHELL_WORKING_DIR = Path(os.getenv("FORGE_WORKING_DIR", str(Path(__file__).resolve().parent.parent)))  # defaults to repo root

# ── Arena ──────────────────────────────────────────────────────────────────
ARENA_MASTER_MODEL = PLANNER_MODEL       # 16-agent Pantheon for commentary/judging
ARENA_DEFAULT_FIGHTER_MODEL = "grok-4-1-fast-reasoning"
ARENA_FIGHTER_AGENT_COUNT = 4
ARENA_RECON_ITERATIONS = 3               # tool iterations for recon round
ARENA_FORGE_ITERATIONS = 5               # tool iterations for weapon forge round
ARENA_COMBAT_TURNS = 6                   # total turns in combat (3 per team)
