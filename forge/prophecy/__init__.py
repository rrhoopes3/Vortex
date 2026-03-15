"""The Prophecy Engine — Swarm-intelligence prediction simulations for The Forge.

Inspired by MiroFish's multi-agent social simulation architecture, the Prophecy
Engine runs self-contained prediction simulations using the Forge's LLM providers.
Diverse AI agents ("prophets") debate, argue, and evolve their positions over
multiple rounds of social interaction to produce emergent predictions.

Usage (programmatic):
    from forge.prophecy import run_prophecy

    sim = run_prophecy(
        topic="Will the Fed cut rates in Q3 2026?",
        seed_material="Recent CPI data shows inflation at 2.1%...",
        num_prophets=12,
        num_rounds=8,
    )
    print(sim.prediction)
    print(sim.final_report)

Usage (as Forge tool):
    The prophecy tools are automatically registered in the Forge's tool registry:
    - prophecy_create: Create and seed a new simulation
    - prophecy_run: Execute the simulation rounds
    - prophecy_report: Generate the prediction report
    - prophecy_status: Check simulation progress
    - prophecy_interview: Chat with a specific prophet
    - prophecy_list: List all simulations
"""

from forge.prophecy.engine import (
    run_prophecy,
    seed_simulation,
    run_simulation,
    generate_report,
    interview_prophet,
    list_simulations,
    load_simulation,
)
from forge.prophecy.types import (
    DeliberationMode,
    ProphecySimulation,
    ProphecyWorld,
    Prophet,
    ProphecyReport,
    RoundState,
    SimulationStatus,
    SimulationType,
)

__all__ = [
    # Pipeline
    "run_prophecy",
    "seed_simulation",
    "run_simulation",
    "generate_report",
    "interview_prophet",
    # Management
    "list_simulations",
    "load_simulation",
    # Types
    "ProphecySimulation",
    "ProphecyWorld",
    "Prophet",
    "ProphecyReport",
    "RoundState",
    "SimulationStatus",
    "SimulationType",
    "DeliberationMode",
]
