"""
Golden eval cases — one canonical eval per capability pack.

Import all golden cases and provide helpers for pack-scoped eval runs.
"""
from forge.eval import EvalCase

# ── Research Pack ────────────────────────────────────────────────────────

RESEARCH_GOLDEN = EvalCase(
    name="golden_research",
    task=(
        "Research the latest developments in quantum error correction. "
        "Produce a structured summary with at least 3 key findings and citations."
    ),
    expected_outputs=["quantum", "error correction"],
    expected_tools=["grep_files", "read_file"],
    max_tool_calls=10,
    max_cost_usd=2.0,
    max_steps=10,
    tags=["golden", "research"],
)

# ── Builder Pack ─────────────────────────────────────────────────────────

BUILDER_GOLDEN = EvalCase(
    name="golden_builder",
    task=(
        "Create a Python CLI tool at /tmp/forge_eval_csv2json.py that converts "
        "CSV files to JSON with column type inference (int, float, string). "
        "Include a --pretty flag for formatted output. Then verify it works by "
        "creating a test CSV and converting it."
    ),
    expected_outputs=["csv", "json"],
    expected_tools=["write_file", "run_command"],
    expected_files=["/tmp/forge_eval_csv2json.py"],
    max_tool_calls=15,
    max_cost_usd=5.0,
    max_steps=15,
    tags=["golden", "builder"],
)

# ── Ops Pack ─────────────────────────────────────────────────────────────

OPS_GOLDEN = EvalCase(
    name="golden_ops",
    task=(
        "Check git status, find all TODO comments in the forge/ directory, "
        "and generate a summary report listing each TODO with its file and line number."
    ),
    expected_outputs=["TODO"],
    expected_tools=["run_command", "grep_files"],
    max_tool_calls=10,
    max_cost_usd=3.0,
    max_steps=10,
    tags=["golden", "ops"],
)

# ── Trading Pack ─────────────────────────────────────────────────────────

TRADING_GOLDEN = EvalCase(
    name="golden_trading",
    task=(
        "Check current portfolio positions and calculate the put/call ratio for SPY. "
        "Report the PCR value, current positions, and any trading signals."
    ),
    expected_outputs=["SPY", "portfolio"],
    expected_tools=["get_portfolio", "get_pcr"],
    max_tool_calls=5,
    max_cost_usd=1.0,
    max_steps=5,
    tags=["golden", "trading"],
)

# ── Arena Pack ───────────────────────────────────────────────────────────

ARENA_GOLDEN = EvalCase(
    name="golden_arena",
    task=(
        "Set up a code golf arena battle between two agents on FizzBuzz. "
        "Configure the battle parameters and describe the expected flow."
    ),
    expected_outputs=["FizzBuzz", "arena"],
    expected_tools=["list_directory", "write_file"],
    max_tool_calls=20,
    max_cost_usd=10.0,
    max_steps=20,
    tags=["golden", "arena"],
)

# ── Email Pack ───────────────────────────────────────────────────────────

EMAIL_GOLDEN = EvalCase(
    name="golden_email",
    task=(
        "Check DMARC status for the configured email domain and list "
        "recent email sending logs. Report any delivery issues."
    ),
    expected_outputs=["DMARC", "email"],
    expected_tools=["run_command"],
    max_tool_calls=5,
    max_cost_usd=1.0,
    max_steps=5,
    tags=["golden", "email"],
)

# ── Arena-Specific Eval Cases (from Grok) ────────────────────────────────

ARENA_COMBAT_SMOKE = EvalCase(
    name="arena_combat_smoke",
    task=(
        "Run a minimal arena combat smoke test: create battlefield directory, "
        "seed a classic scenario with two agents, and verify the sandbox "
        "structure contains battlefield/, red/, and blue/ directories."
    ),
    expected_outputs=["battlefield", "red", "blue"],
    expected_tools=["list_directory", "run_command"],
    max_tool_calls=10,
    max_cost_usd=2.0,
    max_steps=10,
    tags=["golden", "arena", "smoke"],
)

ARENA_MARKETPLACE_RELAY = EvalCase(
    name="arena_marketplace_relay",
    task=(
        "List available marketplace agents, verify the relay invoke mechanism "
        "works by checking the marketplace registry, and confirm toll deduction "
        "tracking is operational."
    ),
    expected_outputs=["marketplace", "toll"],
    expected_tools=["list_directory", "read_file"],
    max_tool_calls=10,
    max_cost_usd=2.0,
    max_steps=10,
    tags=["golden", "arena", "marketplace"],
)

# ── Aggregates ───────────────────────────────────────────────────────────

# One golden eval per pack — the core regression set
PACK_GOLDEN_MAP: dict[str, EvalCase] = {
    "research": RESEARCH_GOLDEN,
    "builder": BUILDER_GOLDEN,
    "ops": OPS_GOLDEN,
    "trading": TRADING_GOLDEN,
    "arena": ARENA_GOLDEN,
    "email": EMAIL_GOLDEN,
}

# All golden evals including arena-specific cases
ALL_GOLDEN_EVALS: list[EvalCase] = [
    RESEARCH_GOLDEN,
    BUILDER_GOLDEN,
    OPS_GOLDEN,
    TRADING_GOLDEN,
    ARENA_GOLDEN,
    EMAIL_GOLDEN,
    ARENA_COMBAT_SMOKE,
    ARENA_MARKETPLACE_RELAY,
]


def get_golden_evals(pack_name: str = "") -> list[EvalCase]:
    """Get golden eval cases, optionally filtered by pack name."""
    if not pack_name:
        return ALL_GOLDEN_EVALS
    cases = [c for c in ALL_GOLDEN_EVALS if pack_name in c.tags]
    if not cases and pack_name in PACK_GOLDEN_MAP:
        cases = [PACK_GOLDEN_MAP[pack_name]]
    return cases
