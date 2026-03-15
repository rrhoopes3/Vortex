"""Forge tool bindings for the Prophecy Engine.

Exposes the swarm-intelligence prediction engine as standard Forge tools that
the executor can call during task execution.

Tools:
    prophecy_create   — Seed a new simulation (generates world + prophets)
    prophecy_run      — Execute simulation rounds
    prophecy_report   — Generate the prediction report from a completed simulation
    prophecy_full     — Full pipeline: seed → simulate → report in one call
    prophecy_status   — Check simulation status and progress
    prophecy_interview — Interview a specific prophet in-character
    prophecy_list     — List all saved simulations
    prophecy_inject   — Inject a breaking event into a running simulation
"""
from __future__ import annotations

import json
import threading
from .registry import ToolRegistry


# ── Background runner for long simulations ───────────────────────────────────

_running_sims: dict[str, threading.Thread] = {}
_sim_logs: dict[str, list[str]] = {}


def _log_for(sim_id: str, msg: str):
    _sim_logs.setdefault(sim_id, []).append(msg)


# ── Tool Implementations ─────────────────────────────────────────────────────

def prophecy_create(
    topic: str,
    seed_material: str = "",
    num_prophets: int = 12,
    num_rounds: int = 8,
    model: str = "",
) -> str:
    """Create and seed a new prophecy simulation (generates world + agents)."""
    try:
        from forge.prophecy.engine import seed_simulation, PROPHECY_DIR
        from forge.prophecy.types import ProphecySimulation

        sim = ProphecySimulation(
            seed_topic=topic,
            seed_material=seed_material,
            num_prophets=num_prophets,
            num_rounds=num_rounds,
            model=model,
        )

        logs = []
        seed_simulation(sim, progress_cb=lambda msg: logs.append(msg))

        return json.dumps({
            "status": "ok",
            "simulation_id": sim.id,
            "topic": sim.world.topic if sim.world else topic,
            "simulation_type": sim.world.simulation_type if sim.world else "unknown",
            "possible_outcomes": sim.world.possible_outcomes if sim.world else [],
            "prophets": [
                {
                    "id": p.id,
                    "name": p.name,
                    "role": p.role,
                    "archetype": p.personality.archetype,
                    "initial_position": p.initial_position[:150],
                    "confidence": p.confidence,
                }
                for p in sim.prophets
            ],
            "log": logs[-10:],
            "next_step": f"Run the simulation with: prophecy_run(simulation_id=\"{sim.id}\")",
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_run(simulation_id: str) -> str:
    """Execute simulation rounds for an existing (seeded) simulation."""
    try:
        from forge.prophecy.engine import load_simulation, run_simulation

        sim = load_simulation(simulation_id)
        if not sim:
            return json.dumps({"error": f"Simulation not found: {simulation_id}"})

        if sim.status.value not in ("created", "seeding", "paused"):
            if sim.status.value == "completed":
                return json.dumps({
                    "status": "already_completed",
                    "simulation_id": sim.id,
                    "rounds_completed": len(sim.rounds),
                    "prediction": sim.prediction[:300],
                })
            if sim.status.value == "running":
                return json.dumps({"status": "already_running", "simulation_id": sim.id})

        logs = []
        round_summaries = []

        def on_round(rs):
            round_summaries.append({
                "round": rs.round_number,
                "key_moment": rs.key_moment,
                "consensus": rs.consensus_score,
                "polarization": rs.polarization_score,
                "actions": len(rs.actions),
            })

        run_simulation(sim, progress_cb=lambda msg: logs.append(msg), round_cb=on_round)

        return json.dumps({
            "status": "ok",
            "simulation_id": sim.id,
            "rounds_completed": len(sim.rounds),
            "rounds": round_summaries,
            "consensus_trajectory": [f"{c:.0%}" for c in sim.consensus_trajectory],
            "log": logs[-15:],
            "next_step": f"Generate the report with: prophecy_report(simulation_id=\"{sim.id}\")",
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_report(simulation_id: str) -> str:
    """Generate prediction report from a completed simulation."""
    try:
        from forge.prophecy.engine import load_simulation, generate_report

        sim = load_simulation(simulation_id)
        if not sim:
            return json.dumps({"error": f"Simulation not found: {simulation_id}"})

        if not sim.rounds:
            return json.dumps({"error": "Simulation has no completed rounds. Run it first."})

        report = generate_report(sim, progress_cb=lambda msg: _log_for(simulation_id, msg))

        return json.dumps({
            "status": "ok",
            "simulation_id": sim.id,
            "prediction": report.prediction,
            "confidence": report.confidence,
            "executive_summary": report.executive_summary,
            "key_findings": report.key_findings,
            "dissenting_views": report.dissenting_views,
            "risk_factors": report.risk_factors,
            "full_report_markdown": sim.final_report,
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_full(
    topic: str,
    seed_material: str = "",
    num_prophets: int = 12,
    num_rounds: int = 8,
    model: str = "",
    events: str = "",
) -> str:
    """Full prophecy pipeline: seed → simulate → report in one call.

    This is the all-in-one tool. For large simulations (many rounds/prophets),
    consider using prophecy_create + prophecy_run + prophecy_report separately
    for better progress visibility.
    """
    try:
        from forge.prophecy.engine import run_prophecy

        parsed_events = None
        if events:
            try:
                parsed_events = json.loads(events)
            except json.JSONDecodeError:
                pass

        logs = []
        sim = run_prophecy(
            topic=topic,
            seed_material=seed_material,
            num_prophets=num_prophets,
            num_rounds=num_rounds,
            model=model,
            events=parsed_events,
            progress_cb=lambda msg: logs.append(msg),
        )

        # Build prophet summary
        prophet_summary = []
        for p in sim.prophets:
            prophet_summary.append({
                "name": p.name,
                "archetype": p.personality.archetype,
                "final_position": p.current_position[:150],
                "confidence": p.confidence,
            })

        # Build round highlights
        round_highlights = []
        for rs in sim.rounds:
            round_highlights.append({
                "round": rs.round_number,
                "key_moment": rs.key_moment,
                "consensus": rs.consensus_score,
            })

        return json.dumps({
            "status": "ok",
            "simulation_id": sim.id,
            "prediction": sim.prediction,
            "confidence": sim.prediction_confidence,
            "prophets": prophet_summary,
            "round_highlights": round_highlights,
            "consensus_trajectory": [f"{c:.0%}" for c in sim.consensus_trajectory],
            "full_report_markdown": sim.final_report,
            "interview_hint": f"Interview any prophet with: prophecy_interview(simulation_id=\"{sim.id}\", prophet_name=\"...\", question=\"...\")",
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_status(simulation_id: str) -> str:
    """Check the status and progress of a simulation."""
    try:
        from forge.prophecy.engine import load_simulation

        sim = load_simulation(simulation_id)
        if not sim:
            return json.dumps({"error": f"Simulation not found: {simulation_id}"})

        result = {
            "status": sim.status.value,
            "simulation_id": sim.id,
            "topic": sim.seed_topic[:200],
            "prophets": len(sim.prophets),
            "rounds_completed": len(sim.rounds),
            "rounds_total": sim.num_rounds,
            "created_at": sim.created_at,
        }

        if sim.prediction:
            result["prediction"] = sim.prediction[:300]
            result["confidence"] = sim.prediction_confidence

        if sim.consensus_trajectory:
            result["consensus_trajectory"] = [f"{c:.0%}" for c in sim.consensus_trajectory]

        if sim.rounds:
            last = sim.rounds[-1]
            result["last_round"] = {
                "round": last.round_number,
                "key_moment": last.key_moment,
                "consensus": last.consensus_score,
                "opinion_distribution": last.opinion_distribution,
            }

        if sim.error:
            result["error"] = sim.error

        # Include recent logs if available
        logs = _sim_logs.get(simulation_id, [])
        if logs:
            result["recent_log"] = logs[-10:]

        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_interview(simulation_id: str, prophet_name: str, question: str) -> str:
    """Interview a specific prophet — they respond in-character based on the simulation."""
    try:
        from forge.prophecy.engine import load_simulation, interview_prophet

        sim = load_simulation(simulation_id)
        if not sim:
            return json.dumps({"error": f"Simulation not found: {simulation_id}"})

        response = interview_prophet(sim, prophet_name, question)

        # Find the prophet for metadata
        prophet = None
        for p in sim.prophets:
            if p.name.lower() == prophet_name.lower() or p.id == prophet_name:
                prophet = p
                break

        result = {
            "status": "ok",
            "prophet": prophet_name,
            "response": response,
        }
        if prophet:
            result["prophet_info"] = {
                "name": prophet.name,
                "role": prophet.role,
                "archetype": prophet.personality.archetype,
                "current_position": prophet.current_position[:200],
                "confidence": prophet.confidence,
            }

        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_list() -> str:
    """List all saved prophecy simulations."""
    try:
        from forge.prophecy.engine import list_simulations
        sims = list_simulations()
        return json.dumps({"status": "ok", "simulations": sims, "count": len(sims)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def prophecy_inject(simulation_id: str, title: str, description: str, round_number: int = 0) -> str:
    """Inject a breaking event into a simulation (affects the next unplayed round)."""
    try:
        from forge.prophecy.engine import load_simulation, PROPHECY_DIR
        from forge.prophecy.types import WorldEvent

        sim = load_simulation(simulation_id)
        if not sim:
            return json.dumps({"error": f"Simulation not found: {simulation_id}"})

        # Default to next round
        if round_number <= 0:
            round_number = len(sim.rounds) + 1

        event = WorldEvent(
            round_number=round_number,
            title=title,
            description=description,
            impact="User-injected event",
            injected_by="user",
        )
        sim.injected_events.append(event)
        sim.save(PROPHECY_DIR)

        return json.dumps({
            "status": "ok",
            "event_injected": {
                "title": title,
                "description": description,
                "round": round_number,
            },
            "total_events": len(sim.injected_events),
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ── Registration ─────────────────────────────────────────────────────────────

def register(registry: ToolRegistry):
    """Register all prophecy tools with the Forge's tool registry."""

    registry.register(
        name="prophecy_create",
        description=(
            "Create a new Prophecy Engine simulation. Generates a world model and "
            "diverse AI agents ('prophets') who will debate and predict outcomes "
            "through multi-round social interaction. Returns the simulation ID, "
            "world context, and prophet roster. Use prophecy_run next to execute."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The question or topic to predict (e.g., 'Will the Fed cut rates in Q3 2026?')",
                },
                "seed_material": {
                    "type": "string",
                    "description": "Optional background data: articles, statistics, context documents. Max ~8K chars.",
                },
                "num_prophets": {
                    "type": "integer",
                    "description": "Number of AI agents (default 12). More = richer simulation, higher cost.",
                    "default": 12,
                },
                "num_rounds": {
                    "type": "integer",
                    "description": "Number of simulation rounds (default 8). More = deeper convergence.",
                    "default": 8,
                },
                "model": {
                    "type": "string",
                    "description": "LLM model to use (empty = auto-select best available).",
                },
            },
            "required": ["topic"],
        },
        handler=prophecy_create,
    )

    registry.register(
        name="prophecy_run",
        description=(
            "Execute the simulation rounds for a seeded prophecy. Prophets interact, "
            "debate, form alliances, and evolve their positions. Returns round-by-round "
            "summaries and consensus trajectory. Use prophecy_report after to generate "
            "the prediction."
        ),
        parameters={
            "type": "object",
            "properties": {
                "simulation_id": {
                    "type": "string",
                    "description": "The simulation ID from prophecy_create.",
                },
            },
            "required": ["simulation_id"],
        },
        handler=prophecy_run,
    )

    registry.register(
        name="prophecy_report",
        description=(
            "Generate a structured prediction report from a completed simulation. "
            "Analyzes the full transcript to extract the emergent prediction, "
            "consensus analysis, dissenting views, and risk factors. Returns a "
            "full Markdown report."
        ),
        parameters={
            "type": "object",
            "properties": {
                "simulation_id": {
                    "type": "string",
                    "description": "The simulation ID from prophecy_create.",
                },
            },
            "required": ["simulation_id"],
        },
        handler=prophecy_report,
    )

    registry.register(
        name="prophecy_full",
        description=(
            "Run the FULL prophecy pipeline in one call: create world + agents, "
            "simulate all rounds, then generate prediction report. Best for quick "
            "predictions. For large simulations, use the step-by-step tools instead. "
            "Returns the complete prediction with confidence, report, and prophet positions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The question or topic to predict.",
                },
                "seed_material": {
                    "type": "string",
                    "description": "Optional background data / context.",
                },
                "num_prophets": {
                    "type": "integer",
                    "description": "Number of AI agents (default 12).",
                    "default": 12,
                },
                "num_rounds": {
                    "type": "integer",
                    "description": "Number of simulation rounds (default 8).",
                    "default": 8,
                },
                "model": {
                    "type": "string",
                    "description": "LLM model to use (empty = auto).",
                },
                "events": {
                    "type": "string",
                    "description": 'JSON array of events to inject: [{"round": 3, "title": "...", "description": "..."}]',
                },
            },
            "required": ["topic"],
        },
        handler=prophecy_full,
    )

    registry.register(
        name="prophecy_status",
        description=(
            "Check the status and progress of a prophecy simulation. Returns "
            "rounds completed, consensus trajectory, last round summary, and "
            "prediction if available."
        ),
        parameters={
            "type": "object",
            "properties": {
                "simulation_id": {
                    "type": "string",
                    "description": "The simulation ID to check.",
                },
            },
            "required": ["simulation_id"],
        },
        handler=prophecy_status,
    )

    registry.register(
        name="prophecy_interview",
        description=(
            "Interview a specific prophet from a simulation. The AI responds fully "
            "in-character as that agent, drawing on their background, personality, "
            "memories from the simulation, and final position. Great for drilling "
            "into specific perspectives."
        ),
        parameters={
            "type": "object",
            "properties": {
                "simulation_id": {
                    "type": "string",
                    "description": "The simulation ID.",
                },
                "prophet_name": {
                    "type": "string",
                    "description": "The prophet's name or ID to interview.",
                },
                "question": {
                    "type": "string",
                    "description": "The question to ask the prophet.",
                },
            },
            "required": ["simulation_id", "prophet_name", "question"],
        },
        handler=prophecy_interview,
    )

    registry.register(
        name="prophecy_list",
        description="List all saved prophecy simulations with their status, topic, and prediction summary.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=prophecy_list,
    )

    registry.register(
        name="prophecy_inject",
        description=(
            "Inject a breaking event into a prophecy simulation. The event will "
            "affect the specified round (or the next unplayed round). Use this to "
            "introduce surprises, breaking news, or scenario changes mid-simulation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "simulation_id": {
                    "type": "string",
                    "description": "The simulation ID.",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the event.",
                },
                "description": {
                    "type": "string",
                    "description": "Full description of what happened and its implications.",
                },
                "round_number": {
                    "type": "integer",
                    "description": "Which round to inject this event (0 = next unplayed round).",
                    "default": 0,
                },
            },
            "required": ["simulation_id", "title", "description"],
        },
        handler=prophecy_inject,
    )
