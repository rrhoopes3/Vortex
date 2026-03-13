# Forge: Capability Packs — Cross-Team Plan

**Status:** Draft for review (Claude, Grok, GPT)
**Date:** 2026-03-13
**Branch context:** `claude/sweet-wescoff` (planning), `claude/xenodochial-tu` (trading fixes @ f6c6412)

---

## The Problem

Forge has ~30 tools, 5 providers, an arena, a marketplace, a trading engine, an email agent, generative UI, and an eval framework. They all work, but they're wired together with individual config bools and hardcoded tool categories. There's no unified concept of "I want to do research" vs "I want to trade" vs "I want to run a battle." The user has to know which tools exist and how to configure them.

GPT's framing nails it: **we need to build the hinge, not add another blade.**

---

## What We're Building

### Capability Packs

A **capability pack** is a declarative unit that bundles everything needed for a specific mode of operation:

```python
@dataclass
class CapabilityPack:
    name: str                          # "research", "builder", "ops", "trading", "arena", "email"
    description: str                   # Human-readable purpose
    tools: list[str]                   # Tool allowlist (names or categories)
    default_model: str                 # Preferred executor model
    fallback_models: list[str]         # Ordered fallback chain
    guardrail_profile: str             # "strict", "standard", "permissive"
    budget: Budget                     # Max cost, max iterations, max tokens
    ui_panels: list[str]              # Which UI panels to show
    env_required: list[str]            # Env vars that MUST be set
    env_optional: list[str]            # Env vars that enhance but aren't required
    deps_required: list[str]           # Python packages needed
    readiness: Callable[[], ReadinessReport]  # Runtime health check
```

### Readiness Panel

Before entering a mode, users see:

```
╔══════════════════════════════════════════╗
║  Trading Mode                            ║
║  ✅ Provider: xAI (grok-4.1-fast)       ║
║  ✅ Tradier API key configured           ║
║  ⚠️  Tradier account_id missing          ║
║     (paper trading only)                 ║
║  ✅ yfinance available                   ║
║  ❌ Solana watcher disabled              ║
║     (set SOLANA_WATCHER_ENABLED=true)    ║
║                                          ║
║  Status: DEGRADED — paper trading only   ║
╚══════════════════════════════════════════╝
```

Readiness states: `READY` | `DEGRADED` (partial function) | `UNAVAILABLE` (missing critical deps)

### Golden Task Evals

One canonical eval flow per pack. These serve as:
- **Regression tests** for the pack's core path
- **Provider comparison benchmarks** (quality, latency, cost across models)
- **CI gates** before merging changes that touch a pack's tools

---

## Architecture

### Where It Lives

```
forge/
├── packs/
│   ├── __init__.py          # CapabilityPack dataclass, PackRegistry
│   ├── research.py          # Research pack definition
│   ├── builder.py           # Builder/coding pack
│   ├── ops.py               # DevOps/infrastructure pack
│   ├── trading.py           # Trading pack
│   ├── arena.py             # Arena combat/collab pack
│   └── email.py             # Email agent pack
├── readiness.py             # ReadinessReport, health probe logic
└── evals/
    ├── golden/
    │   ├── research.py      # Golden eval for research pack
    │   ├── builder.py       # Golden eval for builder pack
    │   ├── trading.py       # Golden eval for trading pack
    │   └── ...
    └── runner.py            # Extended EvalRunner (already exists in eval.py)
```

### How It Integrates

**1. Tool Registry** (`tools/registry.py`)
- `resolve_tools_for_step()` already does category→tool expansion
- Packs call this with their `tools` allowlist
- No tool code changes needed — packs are a layer above

**2. Orchestrator** (`orchestrator.py`)
- `run_task()` gains an optional `pack: str` parameter
- If set, loads pack → injects tool allowlist, model, budget, guardrail profile
- If not set, current behavior (all tools, default model) is preserved
- Auto-detection: planner can suggest a pack based on task analysis

**3. Config** (`config.py`)
- Feature bools remain (backward compat) but packs read them
- Pack readiness checks reference the same env vars
- No config migration needed

**4. API Surface** (`app.py`)
- `GET /api/packs` — list all packs with readiness status
- `POST /api/task` gains optional `"pack": "trading"` field
- `GET /api/packs/<name>/eval` — run golden eval for a pack

**5. Frontend**
- Mode selector in UI (replaces raw task submission)
- Readiness badges per pack
- Pack-specific UI panels (e.g., trading shows portfolio, arena shows scoreboard)

---

## The Six Initial Packs

### 1. Research
- **Tools:** filesystem, search, http, python, clipboard
- **Model:** grok-4.1-fast-reasoning (needs extended thinking)
- **Guardrails:** standard
- **Budget:** $2 / 10 steps
- **Env required:** XAI_API_KEY (or any provider key)
- **Golden eval:** "Research the latest developments in quantum error correction and produce a structured summary with citations"

### 2. Builder
- **Tools:** filesystem, search, shell, python, git, http
- **Model:** grok-4.1-fast-reasoning
- **Guardrails:** standard
- **Budget:** $5 / 15 steps
- **Env required:** any provider key
- **Golden eval:** "Create a Python CLI tool that converts CSV files to JSON with column type inference"

### 3. Ops
- **Tools:** filesystem, search, shell, git, http, database
- **Model:** grok-4.1-fast (speed over depth)
- **Guardrails:** strict (destructive command blocking)
- **Budget:** $3 / 10 steps
- **Env required:** any provider key
- **Golden eval:** "Check git status, find all TODO comments in the codebase, and generate a summary report"

### 4. Trading
- **Tools:** trading tools (buy/sell/portfolio/pcr), http, python, filesystem
- **Model:** grok-4.1-fast-reasoning
- **Guardrails:** strict (financial operations)
- **Budget:** $1 / 5 steps (tight — trading should be precise)
- **Env required:** FORGE_TRADIER_API_KEY
- **Env optional:** FORGE_TRADIER_ACCOUNT_ID (paper trading without it)
- **Golden eval:** "Check current portfolio positions and calculate the put/call ratio for SPY"

### 5. Arena
- **Tools:** filesystem, search, shell, python, git, browser, generative_ui
- **Model:** per-fighter config (already handled by arena runner)
- **Guardrails:** permissive (arena is a sandbox)
- **Budget:** $10 / 20 steps per fighter
- **Env required:** XAI_API_KEY (Pantheon judging needs multi-agent)
- **Golden eval:** "Run a code golf battle between grok-4.1-fast and claude-sonnet on FizzBuzz"

### 6. Email
- **Tools:** email tools, http, filesystem, python
- **Model:** grok-4.1-fast
- **Guardrails:** strict (external communication)
- **Budget:** $1 / 5 steps
- **Env required:** ARC_RELAY_API_KEY, FORGE_EMAIL_DOMAIN
- **Golden eval:** "Check DMARC status for the configured domain and list recent email logs"

---

## Before This: Harden Xenodochial-Tu

GPT flagged two edge cases in the trading fixes (f6c6412) that should be cleaned before merge:

### Edge Case 1: Mark-to-Market with Quote = 0
**Problem:** `portfolio.mark_to_market()` treats a quote of `0` as a valid price. A stock returning `$0.00` from the API likely means "data unavailable" not "worthless."
**Fix:** Treat `quote <= 0` as unavailable, skip that position's revaluation, log a warning.

### Edge Case 2: Provider Readiness with Partial Credentials
**Problem:** Provider config check says "configured" if any credential is present. Tradier needs both API key AND account ID for live trading.
**Fix:** Readiness check should validate the **full credential set** per provider. This naturally feeds into the pack readiness system.

### Regression Tests Needed
Lock in the f6c6412 fixes with explicit test cases:
- `test_mark_to_market_zero_quote` — quote=0 treated as unavailable
- `test_mark_to_market_negative_quote` — same
- `test_provider_readiness_partial_creds` — missing account_id = DEGRADED not READY
- `test_portfolio_refresh_stale_cache` — cache invalidation works after fix
- `test_tradier_account_id_required` — operations that need account_id fail gracefully

---

## Execution Order

### Phase 1: Harden — DONE (Claude, 3dc0ce4)
1. ~~Fix mark-to-market: treat quote <= 0 as "data unavailable"~~
2. ~~Add check_trading_readiness() with full credential validation~~
3. ~~13 regression tests (mark-to-market edge cases, provider readiness, provider caching)~~
4. ~~All 69 trading tests passing~~

### Phase 2: Foundation — DONE (Claude, feature/capability-packs)
1. ~~Create `forge/packs/__init__.py` — `CapabilityPack` dataclass, `PackRegistry`~~
2. ~~`ReadinessReport` + probe logic (integrated into CapabilityPack.check_readiness)~~
3. ~~Wire `PackRegistry` into orchestrator (optional `pack` param on `run_task`)~~
4. ~~Add `GET /api/packs` and `GET /api/packs/<name>` endpoints~~

### Phase 3: Pack Definitions — DONE (Claude, feature/capability-packs)
1. ~~Define all 6 packs (research, builder, ops, trading, arena, email)~~
2. ~~Implement readiness checks per pack (env, deps, feature flags, provider keys)~~
3. Add pack selector to frontend (TODO)
4. ~~Write tests for pack loading, readiness checks, tool filtering (32 tests passing)~~

### Phase 4: Golden Evals — DONE (Claude, d4a3b19)
1. ~~Golden eval cases for all 6 packs (research, builder, ops, trading, arena, email)~~
2. ~~PackEvalRunner: pack-scoped execution with readiness gating~~
3. ~~`POST /api/packs/<name>/eval` endpoint (supports chaos + benchmark modes)~~
4. ~~BenchmarkResult: cross-provider comparison with best-model selection~~
5. ~~**Chaos mode**: ChaosConfig with seeded deterministic failure/timeout injection~~
6. ~~**Arena evals**: combat smoke test + marketplace relay eval cases~~
7. ~~43 tests (golden cases, filtering, chaos, benchmarks, runner, budget alignment)~~
8. TODO: Run actual cross-provider benchmarks and store baseline results
9. TODO: TTS commentary verification eval case

---

## What This Enables (Future Blades)

Once packs exist as the packaging primitive, future capabilities slot in cleanly:

- **MCP Server Mode** → Expose packs as MCP tools (`forge_research`, `forge_build`, `forge_trade`)
- **Custom Packs** → Users define their own packs in YAML
- **Pack Composition** → "research + builder" for a hybrid mode
- **Marketplace Packs** → Third-party agents register packs in the marketplace
- **Auto-Routing** → Planner analyzes task → selects pack automatically
- **A2A Protocol** → Each pack maps to an A2A agent card

---

## Division of Labor (Proposed)

This is flexible — adjust based on who's got bandwidth:

| Agent | Focus | Why |
|-------|-------|-----|
| **Grok** | Pack definitions + readiness checks | Knows the xAI provider surface, multi-agent capabilities, and arena internals best |
| **Claude** | Foundation (`CapabilityPack`, `PackRegistry`, orchestrator wiring) | Strong on architecture and type systems |
| **GPT** | Trading hardening + regression tests + golden evals | Already reviewed the trading bugs, knows what to test |

---

## Open Questions

1. **Pack auto-detection:** Should the planner automatically suggest a pack, or should users always choose explicitly? (Could do both — suggest with override.)
2. **Pack composition:** Can a task span multiple packs? (e.g., "research this stock then trade it" = research → trading) If so, how do tool allowlists merge?
3. **Custom packs:** Do we support user-defined packs in this phase, or defer? (Proposed: defer to Phase 5.)
4. **Pack versioning:** Do packs need versions for marketplace distribution? (Proposed: not yet, but design the schema to support it.)

---

## Success Criteria

After Phase 4, we should be able to:
- `POST /api/task {"task": "...", "pack": "trading"}` → runs with trading tools only, trading budget, trading guardrails
- `GET /api/packs` → returns all 6 packs with readiness status
- `GET /api/packs/trading/eval` → runs golden eval, returns scores
- Run the same golden eval across 3+ providers and compare quality/cost/latency
- A broken env var shows `DEGRADED` not a cryptic runtime error
