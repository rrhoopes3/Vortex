# THE FORGE

**The first autonomous agent OS built on xAI's Grok 4.20 multi-agent beta.**

A 16-agent research council plans your task. A tool-wielding executor carries it out. 30+ client-side tools. 4 AI providers. Real-time streaming. Live cost tracking. And a BattleBot Arena where AI teams fight to the death while Zeus narrates.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![Tests](https://img.shields.io/badge/tests-29%20passing-green)

---

## Architecture

```
User Task
    |
    v
[16-Agent Planner] ── Grok 4.20 multi-agent swarm
    |                   web_search, x_search, code_execution
    |                   produces structured execution plan
    v
[Single Executor] ──── 30+ client-side tools
    |                   filesystem, shell, git, browser, HTTP,
    |                   Python REPL, SQLite, image, archive
    |                   routes to: xAI | Anthropic | OpenAI | LM Studio
    v
Result ── streamed live via SSE with cost tracking
```

**Direct Mode** skips the planner entirely for simple tasks.
**Auto Routing** classifies task complexity and picks the cheapest model that can handle it.

---

## What Ships With It

### Task Engine
The core loop. Type a task, get a plan, watch it execute with real tools. File I/O, shell commands, git operations, browser automation, HTTP requests, database queries — all streamed live in a dark-themed web UI.

### BattleBot Arena
Pit two AI teams against each other in a sandboxed deathmatch. Recon, weapon forging, turn-based combat, and a 16-agent Pantheon (Zeus, Athena, Hephaestus, Hermes, Ares, Hades, Apollo) scoring creativity, execution, damage, and style. Enable TTS for dramatic live commentary.

### Presidential Council
A CLI think tank where 16 US Presidents (Washington through Trump) debate modern problems using the Grok 4.20 multi-agent API. Persistent conversation history across sessions.

### Live Cost Ticker
Real-time USD cost tracking in the UI. See exactly what each task costs as it runs. Color-coded (green/amber/red), configurable limits per task and session, click to reset.

### Context Engineering
Five techniques from the [OpenDev paper](https://arxiv.org/abs/2603.05344):

| Technique | Effect |
|---|---|
| **Lazy Tool Discovery** | Only injects tools the planner says are needed (~60% context reduction) |
| **Adaptive Context Compaction** | Older step outputs progressively summarized as context grows |
| **Session Memory** | Learns from completed tasks, recalls relevant knowledge for new ones |
| **Instruction Reminders** | Re-injects task goal every 3 iterations to prevent drift |
| **Auto Model Routing** | Classifies complexity, picks cheap/fast vs powerful model automatically |

---

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
playwright install chromium  # optional, for browser automation
```

### 2. Configure

Create `.env` in the project root:

```env
XAI_API_KEY=your-xai-api-key-here
ANTHROPIC_API_KEY=           # optional
OPENAI_API_KEY=              # optional
LMSTUDIO_BASE_URL=http://localhost:1234/v1  # optional
```

Only `XAI_API_KEY` is required. Other providers are optional.

### 3. Run

```bash
python forge/app.py          # Web UI at http://localhost:5000
python lads_war_room.py      # Presidential Council CLI
```

---

## Multi-Provider Support

The executor routes to 4 different AI backends. Model list is served from the backend — the UI populates dynamically, no hardcoded dropdowns.

| Model | Provider | Cost (in/out per 1M tokens) |
|---|---|---|
| **Auto (smart routing)** | auto | Routes by task complexity |
| Grok 4.20 Reasoning | xAI | $2 / $6 |
| Grok 4.1 Fast Reasoning | xAI | $0.20 / $0.50 |
| Grok 4.1 Fast | xAI | $0.20 / $0.50 |
| Claude Sonnet 4 | Anthropic | $3 / $15 |
| Claude Haiku 4 | Anthropic | $0.80 / $4 |
| GPT-4o | OpenAI | $2.50 / $10 |
| GPT-4o Mini | OpenAI | $0.15 / $0.60 |
| o3-mini | OpenAI | $1.10 / $4.40 |
| LM Studio | Local | Free |

---

## Tools (30+)

| Category | Tools |
|---|---|
| **Filesystem** | `read_file`, `write_file`, `list_directory`, `append_file`, `delete_file` |
| **Search** | `find_files` (glob), `grep_files` (regex) |
| **Shell** | `run_command` (30s timeout) |
| **Python** | `run_python` (execute code, capture stdout/stderr) |
| **Git** | `git_status`, `git_diff`, `git_commit`, `git_log` |
| **HTTP** | `http_get`, `http_post` |
| **Browser** | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_extract_text`, `browser_info` |
| **Database** | `query_sqlite` |
| **Image** | `resize_image`, `convert_image` |
| **Archive** | `zip_files`, `extract_archive` |
| **Clipboard** | `copy_to_clipboard`, `read_clipboard` |

Lazy tool discovery means only the tools relevant to each step are injected into context. Core tools (read, write, list, find, grep, shell) are always available.

---

## Web UI Controls

| Control | Description |
|---|---|
| **Sandbox** toggle | Restricts file/shell ops to a directory (defaults to repo root) |
| **Direct Mode** toggle | Skips the planner, sends task straight to executor |
| **Agents** slider | Number of planner agents (4, 8, 12, or 16) |
| **Model** dropdown | Executor model (populated from backend) |
| **Cost ticker** | Live session cost in USD (click to reset) |
| **KILL** button | Cancels a running task immediately |
| **ARENA** button | Launch BattleBot Arena |

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/task` | Submit a task (returns `task_id`) |
| `GET` | `/api/stream/<id>` | SSE stream of task progress |
| `POST` | `/api/kill/<id>` | Cancel a running task |
| `POST` | `/api/arena` | Launch arena deathmatch |
| `GET` | `/api/models` | Available models with pricing |
| `GET` | `/api/cost` | Session cost and limits |
| `POST` | `/api/cost/reset` | Reset cost counter |
| `GET` | `/api/config` | Default config (sandbox path) |
| `GET` | `/api/history` | Recent completed tasks |
| `GET` | `/api/memory` | Session memory (learned patterns) |
| `POST` | `/api/memory/clear` | Clear session memories |

```bash
curl -X POST http://localhost:5000/api/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Find all TODO comments in the codebase and list them",
    "sandbox_mode": true,
    "sandbox_path": "/path/to/project",
    "direct_mode": false,
    "agent_count": 16,
    "executor_model": "auto"
  }'
```

---

## Project Structure

```
Grok/
  requirements.txt              # Dependencies
  .env                          # API keys (not committed)
  lads_war_room.py              # Presidential Council CLI
  pantheon.md                   # Agent role documentation
  forge/
    app.py                      # Flask web server + API
    config.py                   # Models, pricing, limits, paths
    orchestrator.py             # Planner -> Executor pipeline
    planner.py                  # 16-agent research council
    executor.py                 # Single-agent tool-calling loop
    providers.py                # Multi-provider adapters + cost calculation
    context_engine.py           # Context compaction, session memory, auto routing
    models.py                   # Pydantic data models
    memory.py                   # Task persistence (JSON)
    tools/
      registry.py               # Tool registry + lazy discovery + sandbox enforcement
      filesystem.py, shell.py, python_repl.py, git_ops.py,
      http.py, browser.py, database.py, image.py,
      archive.py, clipboard.py
    arena/
      runner.py                 # Arena deathmatch orchestrator
      sandbox.py                # Arena sandbox setup
    static/
      index.html, style.css, app.js
  tests/
    test_smoke.py               # 29 smoke tests
```

---

## Configuration

```python
# forge/config.py
PLANNER_MODEL = "grok-4.20-multi-agent-experimental-beta-0304"
EXECUTOR_MODEL = "grok-4.20-experimental-beta-0304-reasoning"
EXECUTOR_MAX_ITERATIONS = 15    # per step
SHELL_TIMEOUT_SECONDS = 30

# Cost limits (env vars: FORGE_COST_LIMIT_TASK, FORGE_COST_LIMIT_SESSION)
COST_LIMIT_PER_TASK = 5.00      # USD
COST_LIMIT_PER_SESSION = 50.00  # USD

# forge/context_engine.py
COMPACT_THRESHOLD = 6000        # chars before compaction kicks in
MAX_MEMORIES = 50               # session memory cap

# forge/executor.py
REMINDER_INTERVAL = 3           # re-inject goal every N iterations
```

---

## License

Do whatever you want with it.
