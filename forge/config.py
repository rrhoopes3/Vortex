import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── API Keys ───────────────────────────────────────────────────────────────
XAI_API_KEY = os.getenv("XAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

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
    "ollama:default": {
        "label": "Ollama (Local)", "provider": "Local",
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
RUNS_DIR = DATA_DIR / "runs"

# Ensure data dirs exist
DATA_DIR.mkdir(exist_ok=True)
CONVERSATIONS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(exist_ok=True)
VAULTS_DIR = DATA_DIR / "vaults"
VAULTS_DIR.mkdir(exist_ok=True)

# ── Limits ──────────────────────────────────────────────────────────────────
EXECUTOR_MAX_ITERATIONS = 15  # raised from 10 — context compaction prevents bloat
SHELL_TIMEOUT_SECONDS = 30
SHELL_WORKING_DIR = Path(os.getenv("FORGE_WORKING_DIR", str(Path(__file__).resolve().parent.parent)))  # defaults to repo root

# ── ARC-Relay ─────────────────────────────────────────────────────────────
ARCRELAY_API_URL = os.getenv("FORGE_ARCRELAY_URL", "https://arc-relay.com")
ARCRELAY_WEBHOOK_SECRET = os.getenv("FORGE_ARCRELAY_WEBHOOK_SECRET", "")
ARCRELAY_API_KEY = os.getenv("FORGE_ARCRELAY_API_KEY", "")

# ── Email Agent ──────────────────────────────────────────────────────────
EMAIL_AGENT_ENABLED = os.getenv("FORGE_EMAIL_AGENT_ENABLED", "false").lower() == "true"
EMAIL_AGENT_MODEL = os.getenv("FORGE_EMAIL_AGENT_MODEL", "grok-4-1-fast-non-reasoning")

# ── Toll Protocol ─────────────────────────────────────────────────────────
TOLL_ENABLED = os.getenv("FORGE_TOLL_ENABLED", "true").lower() == "true"
TOLL_DB_PATH = DATA_DIR / "toll_ledger.db"
TOLL_DEFAULT_BALANCE = float(os.getenv("FORGE_TOLL_DEFAULT_BALANCE", "10.0"))  # USD
TOLL_CREATOR_WALLET = os.getenv("FORGE_TOLL_CREATOR_WALLET", "creator")
TOLL_CREATOR_RAKE_PCT = float(os.getenv("FORGE_TOLL_CREATOR_RAKE", "30.0"))   # %

# ── Marketplace (Beat 3) ─────────────────────────────────────────────────
MARKETPLACE_ENABLED = os.getenv("FORGE_MARKETPLACE_ENABLED", "true").lower() == "true"

# ── Generative UI ────────────────────────────────────────────────────────
GENERATIVE_UI_ENABLED = os.getenv("FORGE_GENERATIVE_UI_ENABLED", "true").lower() == "true"
MARKETPLACE_DEFAULT_BALANCE = float(os.getenv("FORGE_MARKETPLACE_DEFAULT_BALANCE", "1.0"))  # USD for new agents
MARKETPLACE_TASK_ESTIMATE = float(os.getenv("FORGE_MARKETPLACE_TASK_ESTIMATE", "0.05"))     # USD per task estimate
MARKETPLACE_BASE_USDC_ADDRESS = os.getenv("FORGE_BASE_USDC_ADDRESS", "")    # Base L2 USDC receiver
MARKETPLACE_SOLANA_USDC_ADDRESS = os.getenv("FORGE_SOLANA_USDC_ADDRESS", "2RzBNDG52n7EhqSeUYksa5eyTb7YJ8b3xvyJLESzY6zf")  # Solana USDC receiver

# ── Solana Watcher (Beat 4) ──────────────────────────────────────────────
SOLANA_WATCHER_ENABLED = os.getenv("FORGE_SOLANA_WATCHER_ENABLED", "false").lower() == "true"
SOLANA_NETWORK = os.getenv("FORGE_SOLANA_NETWORK", "devnet")  # "devnet" | "mainnet-beta"
SOLANA_RPC_URL = os.getenv("FORGE_SOLANA_RPC_URL", "")  # custom RPC; empty = public endpoint
SOLANA_POLL_INTERVAL = int(os.getenv("FORGE_SOLANA_POLL_INTERVAL", "15"))  # seconds
SOLANA_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # mainnet USDC mint
SOLANA_USDC_DECIMALS = 6

# ── Arena ──────────────────────────────────────────────────────────────────
ARENA_MASTER_MODEL = PLANNER_MODEL       # 16-agent Pantheon for commentary/judging
ARENA_DEFAULT_FIGHTER_MODEL = "grok-4-1-fast-reasoning"
ARENA_FIGHTER_AGENT_COUNT = 4
ARENA_RECON_ITERATIONS = 3               # tool iterations for recon round
ARENA_FORGE_ITERATIONS = 5               # tool iterations for weapon forge round
ARENA_COMBAT_TURNS = 6                   # total turns in combat (3 per team)

# ── OpenClaw-RL (arXiv:2603.10165) ───────────────────────────────────────
SIGNALS_ENABLED = os.getenv("FORGE_SIGNALS_ENABLED", "true").lower() == "true"
JUDGE_ENABLED = os.getenv("FORGE_JUDGE_ENABLED", "true").lower() == "true"
JUDGE_MODEL = os.getenv("FORGE_JUDGE_MODEL", "grok-4-1-fast-reasoning")
JUDGE_TIMEOUT_SECONDS = float(os.getenv("FORGE_JUDGE_TIMEOUT", "30.0"))
DIRECTIVES_ENABLED = os.getenv("FORGE_DIRECTIVES_ENABLED", "true").lower() == "true"
USER_CORRECTION_ENABLED = os.getenv("FORGE_USER_CORRECTION_ENABLED", "true").lower() == "true"
CORRECTION_SIMILARITY_THRESHOLD = float(os.getenv("FORGE_CORRECTION_SIMILARITY", "0.6"))
