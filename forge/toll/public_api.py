"""
Public API Blueprint for the agent marketplace.

All routes prefixed with /api/v1/.

External agents:
  1. Register → get API key + wallet
  2. Submit tasks → tolled execution
  3. Stream results → SSE with toll events
  4. Check balance / deposit funds
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from queue import Queue

from flask import Blueprint, Response, g, jsonify, request

from forge.toll.auth import require_api_key

log = logging.getLogger("forge.toll.public_api")

public_bp = Blueprint("public_api", __name__, url_prefix="/api/v1")

# ── Task state for external agents ────────────────────────────────────────
_ext_queues: dict[str, Queue] = {}
_ext_cancel: dict[str, threading.Event] = {}
_ext_results: dict[str, dict] = {}
_ext_task_owners: dict[str, str] = {}  # task_id → agent_id


def _get_ledger():
    from forge.config import TOLL_DB_PATH
    from forge.toll.ledger import Ledger
    # Reuse the module-level singleton pattern
    if not hasattr(_get_ledger, "_instance"):
        _get_ledger._instance = Ledger(TOLL_DB_PATH)
    return _get_ledger._instance


# ── Registration ──────────────────────────────────────────────────────────

@public_bp.route("/agents/register", methods=["POST"])
def register_agent():
    """Register a new external agent. Returns API key + wallet.

    Body: { "name": "my-bot", "owner": "alice" }
    """
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    owner = data.get("owner", "anonymous").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    # Sanitize: lowercase, alphanumeric + hyphens only
    safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower())[:32]
    agent_id = f"ext_{safe_name}"

    ledger = _get_ledger()

    # Check if agent already exists
    existing_keys = ledger.get_api_keys(agent_id)
    active_keys = [k for k in existing_keys if not k.is_revoked]
    if active_keys:
        return jsonify({
            "error": "agent_already_registered",
            "message": f"Agent '{safe_name}' already has an active API key. "
                       "Use your existing key or revoke it first.",
            "agent_id": agent_id,
        }), 409

    # Create wallet + API key + profile
    from forge.config import MARKETPLACE_DEFAULT_BALANCE
    wallet = ledger.get_or_create_wallet(agent_id, owner, MARKETPLACE_DEFAULT_BALANCE)
    api_key = ledger.create_api_key(agent_id, owner)
    description = data.get("description", "").strip()
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    ledger.create_agent_profile(agent_id, safe_name, description, capabilities)

    log.info("Agent registered: %s (owner=%s)", agent_id, owner)

    return jsonify({
        "agent_id": agent_id,
        "api_key": api_key.api_key,
        "wallet": wallet.model_dump(),
    }), 201


@public_bp.route("/agents/me")
@require_api_key
def agent_info():
    """Authenticated agent info — balance, stats, key info."""
    ledger = _get_ledger()
    wallet = ledger.get_wallet(g.agent_id)
    recent_txs = ledger.get_transactions(g.agent_id, limit=10)

    return jsonify({
        "agent_id": g.agent_id,
        "owner_id": g.owner_id,
        "wallet": wallet.model_dump() if wallet else None,
        "recent_transactions": [tx.model_dump() for tx in recent_txs],
    })


# ── Wallet ────────────────────────────────────────────────────────────────

@public_bp.route("/wallet")
@require_api_key
def wallet_details():
    """Wallet details + recent transactions."""
    ledger = _get_ledger()
    wallet = ledger.get_wallet(g.agent_id)
    if not wallet:
        return jsonify({"error": "no wallet found"}), 404
    recent_txs = ledger.get_transactions(g.agent_id, limit=20)
    return jsonify({
        "wallet": wallet.model_dump(),
        "recent_transactions": [tx.model_dump() for tx in recent_txs],
    })


@public_bp.route("/wallet/deposit", methods=["POST"])
@require_api_key
def wallet_deposit():
    """Deposit funds into authenticated agent's wallet."""
    data = request.get_json() or {}
    amount = data.get("amount_usd", 0)
    if amount <= 0:
        return jsonify({"error": "positive amount_usd required"}), 400

    ledger = _get_ledger()
    tx = ledger.deposit(g.agent_id, amount)
    new_balance = ledger.get_balance(g.agent_id)

    return jsonify({
        "transaction": tx.model_dump(),
        "new_balance_usd": new_balance,
    })


# ── Tasks ─────────────────────────────────────────────────────────────────

@public_bp.route("/tasks", methods=["POST"])
@require_api_key
def submit_task():
    """Submit a task for tolled execution.

    Body: { "task": "...", "direct_mode": true/false, "executor_model": "..." }
    """
    from forge.toll.gating import toll_gate
    from forge.config import MARKETPLACE_TASK_ESTIMATE

    # Manual toll gate check (not decorator — need dynamic estimate)
    agent_id = g.agent_id
    ledger = _get_ledger()
    balance = ledger.get_balance(agent_id)

    if balance < MARKETPLACE_TASK_ESTIMATE:
        from forge.config import MARKETPLACE_BASE_USDC_ADDRESS, MARKETPLACE_SOLANA_USDC_ADDRESS
        shortfall = round(MARKETPLACE_TASK_ESTIMATE - balance, 8)
        invoice = ledger.create_invoice(agent_id, MARKETPLACE_TASK_ESTIMATE)
        payment_methods = [
            {"type": "api_deposit", "method": "POST /api/v1/wallet/deposit"},
        ]
        if MARKETPLACE_BASE_USDC_ADDRESS:
            payment_methods.append({
                "type": "base_usdc", "chain_id": 8453,
                "receiver": MARKETPLACE_BASE_USDC_ADDRESS,
            })
        if MARKETPLACE_SOLANA_USDC_ADDRESS:
            payment_methods.append({
                "type": "solana_usdc",
                "receiver": MARKETPLACE_SOLANA_USDC_ADDRESS,
                "memo": invoice.invoice_id,
            })
        return jsonify({
            "error": "payment_required",
            "estimate_usd": MARKETPLACE_TASK_ESTIMATE,
            "current_balance_usd": round(balance, 8),
            "shortfall_usd": shortfall,
            "invoice_id": invoice.invoice_id,
            "payment_methods": payment_methods,
        }), 402

    data = request.get_json() or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task is required"}), 400

    direct_mode = data.get("direct_mode", True)
    executor_model = data.get("executor_model", "").strip()

    task_id = f"ext-{uuid.uuid4().hex[:8]}"
    q = Queue()
    cancel_event = threading.Event()
    _ext_queues[task_id] = q
    _ext_cancel[task_id] = cancel_event
    _ext_task_owners[task_id] = agent_id

    thread = threading.Thread(
        target=_run_ext_task,
        args=(task_id, task, q, cancel_event, agent_id),
        kwargs={
            "direct_mode": direct_mode,
            "executor_model": executor_model,
        },
        daemon=True,
    )
    thread.start()

    log.info("External task %s submitted by %s: %s", task_id, agent_id, task[:80])

    return jsonify({
        "task_id": task_id,
        "stream_url": f"/api/v1/tasks/{task_id}/stream",
        "result_url": f"/api/v1/tasks/{task_id}/result",
    }), 202


def _run_ext_task(task_id: str, task: str, q: Queue, cancel_event: threading.Event,
                  agent_id: str, direct_mode: bool = True, executor_model: str = ""):
    """Background thread for external agent task execution."""
    try:
        from forge.orchestrator import Orchestrator
        from forge.config import SHELL_WORKING_DIR

        orch = Orchestrator(
            sandbox_path=str(SHELL_WORKING_DIR),
            direct_mode=direct_mode,
            cancel_event=cancel_event,
            executor_model=executor_model,
            task_id=task_id,
            toll_sender=agent_id,
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
            _ext_results[task_id] = {
                "task_id": result.task_id,
                "task": result.task,
                "final_summary": result.final_summary,
                "results": [r.model_dump() if hasattr(r, "model_dump") else vars(r)
                            for r in (result.results or [])],
            }

    except Exception as e:
        log.exception("External task %s failed", task_id)
        q.put({"type": "error", "content": f"{type(e).__name__}: {e}"})
    finally:
        q.put(None)  # sentinel


@public_bp.route("/tasks/<task_id>/stream")
@require_api_key
def task_stream(task_id: str):
    """SSE stream for an external task. Includes toll events."""
    # Verify ownership
    owner = _ext_task_owners.get(task_id)
    if owner != g.agent_id:
        return jsonify({"error": "task not found or not owned by you"}), 404

    q = _ext_queues.get(task_id)
    if not q:
        return jsonify({"error": "task not found or already consumed"}), 404

    def generate():
        try:
            while True:
                msg = q.get()
                if msg is None:
                    yield f"data: {json.dumps({'type': 'done', 'final': True})}\n\n"
                    break
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            _ext_queues.pop(task_id, None)
            _ext_cancel.pop(task_id, None)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@public_bp.route("/tasks/<task_id>/result")
@require_api_key
def task_result(task_id: str):
    """Final result for a completed external task + toll summary."""
    owner = _ext_task_owners.get(task_id)
    if owner != g.agent_id:
        return jsonify({"error": "task not found or not owned by you"}), 404

    result = _ext_results.get(task_id)
    if not result:
        # Check if task is still running
        if task_id in _ext_queues:
            return jsonify({"status": "running", "task_id": task_id}), 202
        return jsonify({"error": "result not available"}), 404

    # Get toll summary for this task session
    ledger = _get_ledger()
    toll_summary = ledger.get_session_summary(task_id)

    response = {
        **result,
        "toll_summary": toll_summary.model_dump(),
    }

    # Clean up
    _ext_results.pop(task_id, None)
    _ext_task_owners.pop(task_id, None)

    return jsonify(response)


# ── Deposit Status ────────────────────────────────────────────────────────

@public_bp.route("/wallet/deposit/status/<invoice_id>")
@require_api_key
def deposit_status(invoice_id: str):
    """Check whether a Solana USDC deposit has been matched to an invoice."""
    ledger = _get_ledger()
    inv = ledger.get_invoice(invoice_id)
    if not inv:
        return jsonify({"error": "invoice not found"}), 404
    if inv.agent_id != g.agent_id:
        return jsonify({"error": "invoice not found"}), 404
    return jsonify(inv.model_dump())


# ── Agent Directory + Relay (Beat 5) ─────────────────────────────────────

@public_bp.route("/agents")
def agent_directory():
    """Public agent directory — lists all registered agents with profiles."""
    ledger = _get_ledger()
    profiles = ledger.list_agent_profiles(public_only=True)
    return jsonify([p.model_dump() for p in profiles])


@public_bp.route("/agents/me/profile", methods=["PATCH"])
@require_api_key
def update_profile():
    """Update authenticated agent's profile (description, capabilities, visibility)."""
    data = request.get_json() or {}
    ledger = _get_ledger()
    profile = ledger.update_agent_profile(
        g.agent_id,
        description=data.get("description"),
        capabilities=data.get("capabilities"),
        is_public=data.get("is_public"),
    )
    if not profile:
        return jsonify({"error": "profile not found"}), 404
    return jsonify(profile.model_dump())


@public_bp.route("/agents/<target_agent>/invoke", methods=["POST"])
@require_api_key
def invoke_agent(target_agent: str):
    """Invoke another agent — submits a task billed to the caller.

    Body: { "task": "...", "executor_model": "..." }
    The calling agent pays all tolls. A relay fee is recorded.
    """
    from forge.config import MARKETPLACE_TASK_ESTIMATE

    ledger = _get_ledger()

    # Verify target exists
    target_profile = ledger.get_agent_profile(target_agent)
    if not target_profile:
        return jsonify({"error": "agent not found"}), 404

    if target_agent == g.agent_id:
        return jsonify({"error": "cannot invoke yourself"}), 400

    # Check caller balance
    balance = ledger.get_balance(g.agent_id)
    if balance < MARKETPLACE_TASK_ESTIMATE:
        return jsonify({
            "error": "payment_required",
            "estimate_usd": MARKETPLACE_TASK_ESTIMATE,
            "current_balance_usd": round(balance, 8),
        }), 402

    data = request.get_json() or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task is required"}), 400

    executor_model = data.get("executor_model", "").strip()

    task_id = f"relay-{uuid.uuid4().hex[:8]}"
    q = Queue()
    cancel_event = threading.Event()
    _ext_queues[task_id] = q
    _ext_cancel[task_id] = cancel_event
    _ext_task_owners[task_id] = g.agent_id

    thread = threading.Thread(
        target=_run_ext_task,
        args=(task_id, task, q, cancel_event, g.agent_id),
        kwargs={"direct_mode": True, "executor_model": executor_model},
        daemon=True,
    )
    thread.start()

    log.info("Relay %s: %s → %s task=%s", task_id, g.agent_id, target_agent, task[:60])

    return jsonify({
        "task_id": task_id,
        "relay": {"caller": g.agent_id, "target": target_agent},
        "stream_url": f"/api/v1/tasks/{task_id}/stream",
        "result_url": f"/api/v1/tasks/{task_id}/result",
    }), 202


# ── Info (public) ─────────────────────────────────────────────────────────

@public_bp.route("/toll/rates")
def public_rates():
    """Current toll rate schedule — no auth required."""
    from forge.toll.rates import RateEngine
    engine = RateEngine()
    return jsonify(engine.all_rates())


@public_bp.route("/toll/estimate")
@require_api_key
def toll_estimate():
    """Rough cost estimate for a task."""
    from forge.config import MARKETPLACE_TASK_ESTIMATE
    task = request.args.get("task", "")
    # Simple estimate — could be refined with token counting later
    estimate = MARKETPLACE_TASK_ESTIMATE
    if len(task) > 500:
        estimate *= 2  # longer tasks cost more
    return jsonify({
        "estimate_usd": estimate,
        "note": "Actual cost depends on tokens used and tools invoked",
    })
