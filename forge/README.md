# THE FORGE

**Grok 4.20 Autonomous Agent OS** &mdash; a multi-agent task execution engine with a BattleBot Arena, powered by xAI's multi-agent API.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)

---

## What Is This?

The Forge is a two-tier AI agent system:

1. **Planner** &mdash; A 16-agent research council (Grok 4.20 multi-agent) analyzes your task, searches the web, and produces a structured execution plan.
2. **Executor** &mdash; A single agent carries out each step using 30+ client-side tools (file I/O, shell, git, browser automation, HTTP, database, and more).

It also ships with:
- **BattleBot Arena** &mdash; Pit two AI teams against each other in a sandboxed deathmatch with Zeus as Arena Master.
- **Presidential Council** &mdash; A CLI think tank where 16 US Presidents debate modern problems.

### Context Engineering (OpenDev-Inspired)

The Forge implements five techniques from the [OpenDev paper](https://arxiv.org/abs/2603.05344) for smarter context management:

| Feature | What It Does |
|---|---|
| **Lazy Tool Discovery** | Only injects tools relevant to each step (not all 30+), reducing context size ~60% |
| **Adaptive Context Compaction** | Older step outputs are progressively summarized as context grows |
| **Session Memory** | Learns from completed tasks and recalls relevant knowledge for future ones |
| **Instruction Reminders** | Re-injects the original task goal every 3 iterations to prevent drift |
| **Auto Model Routing** | Classifies task complexity and picks cheap/fast vs powerful model automatically |

---

## Quick Start

### 1. Install Dependencies

```bash
pip install xai-sdk flask anthropic openai python-dotenv pydantic rich playwright pillow
```

For browser automation (optional):
```bash
playwright install chromium
```

### 2. Configure API Keys

Create a `.env` file in the project root:

```env
XAI_API_KEY=your-xai-api-key-here
ANTHROPIC_API_KEY=           # optional, for Claude models
OPENAI_API_KEY=              # optional, for GPT models
LMSTUDIO_BASE_URL=http://localhost:1234/v1  # optional, for local models
```

Only `XAI_API_KEY` is required. The other providers are optional.

### 3. Run The Forge (Web UI)

```bash
python forge/app.py
```

Open **http://localhost:5000** in your browser.

### 4. Run the Presidential Council (CLI)

```bash
python lads_war_room.py
```

---

## Web UI Features

### Task Execution

Type a task in the input bar and hit **FORGE**. The system will:

1. Launch the multi-agent planner (4-16 agents configurable)
2. Stream the plan in real-time
3. Execute each step with tools, streaming output and tool calls live
4. Save results to task history

### Controls

| Control | Description |
|---|---|
| **Sandbox** toggle | Restricts file/shell ops to a directory (default: `B:/Grok`) |
| **Direct Mode** toggle | Skips the planner, sends task straight to executor |
| **Agents** slider | Number of planner agents (4, 8, 12, or 16) |
| **Model** dropdown | Executor model selection (see below) |
| **KILL** button | Cancels a running task immediately |

### Available Executor Models

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
| LM Studio (Local) | Local | Free |

**Auto routing** classifies your task as simple, moderate, or complex and picks the right model:
- Simple/moderate tasks &rarr; Grok 4.1 Fast Reasoning (cheap)
- Complex tasks (refactoring, multi-file, architecture) &rarr; Grok 4.20 Reasoning (powerful)

---

## Tools (30+)

The executor has access to these client-side tools:

| Category | Tools |
|---|---|
| **Filesystem** | `read_file`, `write_file`, `list_directory`, `append_file`, `delete_file` |
| **Search** | `find_files` (glob), `grep_files` (regex) |
| **Shell** | `run_command` (30s timeout) |
| **Python** | `run_python` (execute code, capture stdout/stderr) |
| **Git** | `git_status`, `git_diff`, `git_commit`, `git_log` |
| **HTTP** | `http_get`, `http_post` (6K body cap) |
| **Browser** | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_extract_text`, `browser_info` |
| **Database** | `query_sqlite` |
| **Image** | `resize_image`, `convert_image` |
| **Archive** | `zip_files`, `extract_archive` |
| **Clipboard** | `copy_to_clipboard`, `read_clipboard` |

With **lazy tool discovery**, only the tools relevant to each step are injected into the model's context. Core tools (read, write, list, find, grep, shell) are always available.

---

## BattleBot Arena

Click the **ARENA** button in the web UI to launch a deathmatch:

1. **Pick fighters** &mdash; Choose models for Red and Blue teams
2. **Round 1: Recon** &mdash; Both teams scout the arena sandbox
3. **Round 2: Weapon Forge** &mdash; Teams build scripts, tools, and weapons
4. **Round 3: Combat** &mdash; Turn-based battle with tool execution
5. **Sudden Death** &mdash; If scores are tied
6. **Judgment** &mdash; Zeus and the Pantheon score creativity, execution, damage, and style

Enable **TTS** for dramatic live commentary read aloud.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/task` | Submit a task (returns `task_id`) |
| `GET` | `/api/stream/<id>` | SSE stream of task progress |
| `POST` | `/api/kill/<id>` | Cancel a running task |
| `POST` | `/api/arena` | Launch arena deathmatch |
| `GET` | `/api/history` | Recent completed tasks |
| `GET` | `/api/memory` | View session memory (learned patterns) |
| `POST` | `/api/memory/clear` | Clear all session memories |

### Task Submission

```bash
curl -X POST http://localhost:5000/api/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Find all TODO comments in the codebase and list them",
    "sandbox_mode": true,
    "sandbox_path": "B:/Grok",
    "direct_mode": false,
    "agent_count": 16,
    "executor_model": "auto"
  }'
```

---

## Project Structure

```
Grok/
  .env                          # API keys (not committed)
  lads_war_room.py              # Presidential Council CLI
  pantheon.md                   # Agent role documentation
  forge/
    app.py                      # Flask web server
    config.py                   # Models, limits, paths
    orchestrator.py             # Planner -> Executor pipeline
    planner.py                  # 16-agent research council
    executor.py                 # Single-agent tool-calling loop
    providers.py                # Anthropic/OpenAI/LM Studio adapters
    context_engine.py           # Context compaction, session memory, auto routing
    models.py                   # Pydantic data models
    memory.py                   # Task persistence (JSON)
    tools/
      registry.py               # Tool registry + lazy discovery
      __init__.py                # Tool registration
      filesystem.py             # File read/write/delete/find/grep
      shell.py                  # Shell command execution
      python_repl.py            # Python code execution
      git_ops.py                # Git operations
      http.py                   # HTTP GET/POST
      browser.py                # Playwright browser automation
      database.py               # SQLite queries
      image.py                  # Image resize/convert
      archive.py                # ZIP/TAR operations
      clipboard.py              # System clipboard
    arena/
      runner.py                 # Arena deathmatch orchestrator
      sandbox.py                # Arena sandbox setup
    static/
      index.html                # SPA frontend
      style.css                 # Dark theme UI
      app.js                    # Frontend logic + SSE streaming
    data/                       # Runtime data (gitignored)
      tasks.json                # Task history
      session_memory.json       # Learned patterns across tasks
      conversations/            # Per-task conversation logs
```

---

## Configuration

Key settings in `forge/config.py`:

```python
PLANNER_MODEL = "grok-4.20-multi-agent-experimental-beta-0304"
EXECUTOR_MODEL = "grok-4.20-experimental-beta-0304-reasoning"
PLANNER_AGENT_COUNT = 16
EXECUTOR_MAX_ITERATIONS = 15    # per step (raised from 10 with context compaction)
SHELL_TIMEOUT_SECONDS = 30
```

Context engine settings in `forge/context_engine.py`:

```python
COMPACT_THRESHOLD = 6000        # chars before compaction kicks in
KEEP_RECENT_STEPS = 2           # recent steps kept at full detail
MAX_MEMORIES = 50               # session memory cap
REMINDER_INTERVAL = 3           # re-inject goal every N iterations
```

---

## License

This is a fun project. Do whatever you want with it.
