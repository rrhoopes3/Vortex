"""
Flask web server for The Forge.

Routes:
  GET  /                  → serves the SPA
  POST /api/task          → submit a task, returns task_id
  GET  /api/stream/<id>   → SSE stream of task progress
  POST /api/kill/<id>     → cancel a running task
  GET  /api/history       → recent completed tasks
"""
import sys
import os
import json
import logging
import threading
import uuid
from queue import Queue

from flask import Flask, request, jsonify, Response, send_from_directory

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure forge package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.orchestrator import Orchestrator
from forge.memory import save_task, get_recent_tasks
from forge.models import TaskResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("forge.app")

app = Flask(__name__, static_folder="static", static_url_path="/static")

# ── Task State ──────────────────────────────────────────────────────────────
task_queues: dict[str, Queue] = {}
task_results: dict[str, TaskResult] = {}
task_cancel_events: dict[str, threading.Event] = {}


def run_task(task_id: str, task: str, q: Queue, cancel_event: threading.Event,
             sandbox_path: str = "", direct_mode: bool = False, agent_count: int = 16,
             executor_model: str = ""):
    """Background thread that runs the orchestrator and pushes messages to a queue."""
    try:
        orch = Orchestrator(
            sandbox_path=sandbox_path,
            direct_mode=direct_mode,
            agent_count=agent_count,
            cancel_event=cancel_event,
            executor_model=executor_model,
        )
        gen = orch.run(task)
        result = None
        try:
            while True:
                msg = next(gen)
                q.put(msg)
        except StopIteration as e:
            result = e.value

        if result:
            task_results[task_id] = result
            save_task(result)

    except Exception as e:
        log.exception("Task %s failed", task_id)
        q.put({"type": "error", "content": f"{type(e).__name__}: {e}"})
    finally:
        q.put(None)  # sentinel


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/task", methods=["POST"])
def submit_task():
    data = request.get_json()
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "No task provided"}), 400

    # Settings from frontend
    sandbox_mode = data.get("sandbox_mode", False)
    sandbox_path = data.get("sandbox_path", "").strip() if sandbox_mode else ""
    direct_mode = data.get("direct_mode", False)
    agent_count = data.get("agent_count", 16)
    executor_model = data.get("executor_model", "").strip()

    task_id = str(uuid.uuid4())[:8]
    q = Queue()
    cancel_event = threading.Event()
    task_queues[task_id] = q
    task_cancel_events[task_id] = cancel_event

    thread = threading.Thread(
        target=run_task,
        args=(task_id, task, q, cancel_event),
        kwargs={
            "sandbox_path": sandbox_path,
            "direct_mode": direct_mode,
            "agent_count": agent_count,
            "executor_model": executor_model,
        },
        daemon=True,
    )
    thread.start()

    log.info("Task %s submitted: %s", task_id, task[:80])
    return jsonify({"task_id": task_id})


@app.route("/api/kill/<task_id>", methods=["POST"])
def kill_task(task_id):
    cancel_event = task_cancel_events.get(task_id)
    if not cancel_event:
        return jsonify({"error": "Unknown task_id"}), 404

    cancel_event.set()
    log.info("Task %s kill signal sent", task_id)
    return jsonify({"status": "kill_signal_sent", "task_id": task_id})


@app.route("/api/stream/<task_id>")
def stream(task_id):
    q = task_queues.get(task_id)
    if not q:
        return jsonify({"error": "Unknown task_id"}), 404

    def generate():
        while True:
            msg = q.get()
            if msg is None:
                yield f"data: {json.dumps({'type': 'done', 'final': True})}\n\n"
                break
            yield f"data: {json.dumps(msg)}\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/history")
def history():
    return jsonify(get_recent_tasks())


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("  ╔═══════════════════════════════════════╗")
    print("  ║     THE FORGE — Grok 4.20 Agent OS    ║")
    print("  ║     http://localhost:5000              ║")
    print("  ╚═══════════════════════════════════════╝")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
