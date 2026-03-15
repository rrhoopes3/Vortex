"""Flask Blueprint for Prophecy Engine API endpoints."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from queue import Queue

from flask import Blueprint, Response, jsonify, request

log = logging.getLogger("forge.prophecy.endpoints")

prophecy_bp = Blueprint("prophecy", __name__, url_prefix="/api/prophecy")

# In-flight simulation tracking
_running: dict[str, dict] = {}  # sim_id → {"thread", "cancel", "status", "error"}


@prophecy_bp.route("/simulations")
def list_sims():
    """List all saved simulations."""
    from forge.prophecy import list_simulations
    sims = list_simulations()  # returns list of dicts already
    return jsonify({"simulations": sims})


@prophecy_bp.route("/simulations/<sim_id>")
def get_sim(sim_id: str):
    """Get full simulation state."""
    from forge.prophecy import load_simulation
    sim = load_simulation(sim_id)
    if not sim:
        return jsonify({"error": "Simulation not found"}), 404
    return jsonify(_sim_to_dict(sim))


@prophecy_bp.route("/create", methods=["POST"])
def create_sim():
    """Seed a new simulation (phase 1 only — world + prophets)."""
    data = request.get_json() or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "No topic provided"}), 400

    seed_material = data.get("seed_material", "")
    num_prophets = data.get("num_prophets", 12)
    num_rounds = data.get("num_rounds", 8)

    deliberation_mode = data.get("deliberation_mode", "hivemind")

    from forge.prophecy import seed_simulation
    from forge.prophecy.types import DeliberationMode, ProphecySimulation
    try:
        sim = ProphecySimulation(
            seed_topic=topic,
            seed_material=seed_material,
            num_prophets=num_prophets,
            num_rounds=num_rounds,
            deliberation_mode=DeliberationMode(deliberation_mode),
        )
        sim = seed_simulation(sim)
        return jsonify({
            "id": sim.id,
            "status": sim.status.value,
            "num_prophets": len(sim.prophets),
            "world": sim.world.topic if sim.world else "",
        })
    except Exception as e:
        log.exception("Failed to create simulation")
        return jsonify({"error": str(e)}), 500


@prophecy_bp.route("/run/<sim_id>", methods=["POST"])
def run_sim(sim_id: str):
    """Run simulation rounds (phase 2). Non-blocking — starts background thread."""
    from forge.prophecy import load_simulation, run_simulation

    sim = load_simulation(sim_id)
    if not sim:
        return jsonify({"error": "Simulation not found"}), 404

    if sim_id in _running and _running[sim_id].get("status") == "running":
        return jsonify({"error": "Simulation already running"}), 409

    cancel = threading.Event()
    tracker = {"status": "running", "cancel": cancel, "error": None}
    _running[sim_id] = tracker

    def _bg():
        try:
            run_simulation(sim)
            tracker["status"] = "done"
        except Exception as e:
            log.exception("Simulation %s failed", sim_id)
            tracker["status"] = "error"
            tracker["error"] = str(e)

    t = threading.Thread(target=_bg, daemon=True)
    t.start()

    return jsonify({"status": "started", "id": sim_id})


@prophecy_bp.route("/report/<sim_id>")
def get_report(sim_id: str):
    """Generate or retrieve the prediction report (phase 3)."""
    from forge.prophecy import load_simulation, generate_report

    sim = load_simulation(sim_id)
    if not sim:
        return jsonify({"error": "Simulation not found"}), 404

    if sim.final_report:
        return jsonify({"report": sim.final_report})

    try:
        report = generate_report(sim)
        return jsonify({"report": report.model_dump() if hasattr(report, "model_dump") else str(report)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@prophecy_bp.route("/interview/<sim_id>/<prophet_name>", methods=["POST"])
def interview(sim_id: str, prophet_name: str):
    """Chat with a specific prophet in-character."""
    from forge.prophecy import load_simulation, interview_prophet

    sim = load_simulation(sim_id)
    if not sim:
        return jsonify({"error": "Simulation not found"}), 404

    data = request.get_json() or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    try:
        response = interview_prophet(sim, prophet_name, question)
        return jsonify({"prophet": prophet_name, "response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@prophecy_bp.route("/status/<sim_id>")
def sim_status(sim_id: str):
    """Check simulation progress (including in-flight runs)."""
    from forge.prophecy import load_simulation

    sim = load_simulation(sim_id)
    if not sim:
        return jsonify({"error": "Simulation not found"}), 404

    result = {
        "id": sim.id,
        "status": sim.status.value,
        "rounds_completed": len(sim.rounds),
        "rounds_total": sim.num_rounds,
        "num_prophets": len(sim.prophets),
    }

    # Check in-flight status
    if sim_id in _running:
        result["run_status"] = _running[sim_id]["status"]
        if _running[sim_id].get("error"):
            result["run_error"] = _running[sim_id]["error"]

    return jsonify(result)


@prophecy_bp.route("/full", methods=["POST"])
def run_full():
    """Run the complete pipeline (create + run + report) synchronously."""
    data = request.get_json() or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "No topic provided"}), 400

    from forge.prophecy import run_prophecy
    try:
        sim = run_prophecy(
            topic=topic,
            seed_material=data.get("seed_material", ""),
            num_prophets=data.get("num_prophets", 12),
            num_rounds=data.get("num_rounds", 8),
            deliberation_mode=data.get("deliberation_mode", "hivemind"),
        )
        return jsonify(_sim_to_dict(sim))
    except Exception as e:
        log.exception("Full prophecy pipeline failed")
        return jsonify({"error": str(e)}), 500


def _sim_to_dict(sim) -> dict:
    """Convert a ProphecySimulation to a JSON-safe dict."""
    return {
        "id": sim.id,
        "topic": sim.seed_topic,
        "status": sim.status.value,
        "created_at": sim.created_at,
        "num_prophets": len(sim.prophets),
        "rounds_completed": len(sim.rounds),
        "rounds_total": sim.num_rounds,
        "deliberation_mode": sim.deliberation_mode.value,
        "prediction": sim.prediction,
        "confidence": sim.prediction_confidence,
        "world": {
            "topic": sim.world.topic,
            "context": sim.world.context,
            "simulation_type": sim.world.simulation_type.value,
        } if sim.world else None,
        "prophets": [
            {
                "name": p.name,
                "role": p.role,
                "archetype": p.personality.archetype if p.personality else "",
                "position": p.current_position or p.initial_position,
                "confidence": p.confidence,
                "influence": p.personality.influence if p.personality else 0.5,
            }
            for p in sim.prophets
        ],
        "rounds": [
            {
                "round_number": r.round_number,
                "summary": r.round_summary or r.key_moment,
                "consensus": r.consensus_score,
            }
            for r in sim.rounds
        ],
        "report": sim.final_report if isinstance(sim.final_report, str) else None,
    }
