"""Prophecy Engine — Data types for swarm-intelligence prediction simulations.

Inspired by MiroFish's multi-agent social simulation architecture, adapted to
run entirely within the Forge's LLM providers with no external dependencies.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class SimulationStatus(str, Enum):
    CREATED = "created"
    SEEDING = "seeding"          # generating world + agents
    RUNNING = "running"          # simulation rounds in progress
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionType(str, Enum):
    """Actions an agent can take in a simulation round."""
    POST = "post"                # publish an opinion / analysis
    REPLY = "reply"              # respond to another agent's post
    REACT = "react"              # agree / disagree / amplify
    UPDATE_POSITION = "update"   # change their stance
    LEAK = "leak"                # reveal private information
    ALLIANCE = "alliance"        # form a coalition
    DISSENT = "dissent"          # break from consensus


class SimulationType(str, Enum):
    """The kind of world being simulated."""
    SOCIAL_MEDIA = "social_media"       # Twitter/Reddit style opinion dynamics
    MARKET = "market"                   # Financial market prediction
    GEOPOLITICAL = "geopolitical"       # International relations / policy
    ELECTION = "election"               # Voting / campaign dynamics
    CRISIS = "crisis"                   # Emergency / disaster response
    CUSTOM = "custom"                   # Free-form


class DeliberationMode(str, Enum):
    """How prophets deliberate each round."""
    HIVEMIND = "hivemind"               # One LLM call simulates all prophets (fast, cheap)
    INDEPENDENT = "independent"         # Each prophet gets own LLM call in parallel (richer, costlier)


# ── Agent Models ─────────────────────────────────────────────────────────────

class ProphetPersonality(BaseModel):
    """Personality profile for a simulation agent."""
    archetype: str = ""          # e.g., "Contrarian Analyst", "Herd Follower"
    openness: float = 0.5        # 0–1: how open to changing their mind
    influence: float = 0.5       # 0–1: how much weight others give their opinion
    risk_tolerance: float = 0.5  # 0–1: willingness to make bold predictions
    knowledge_domains: list[str] = Field(default_factory=list)
    biases: list[str] = Field(default_factory=list)  # cognitive biases


class Prophet(BaseModel):
    """A single agent (prophet) in the simulation."""
    id: str = Field(default_factory=lambda: f"prophet_{uuid.uuid4().hex[:8]}")
    name: str
    role: str                    # e.g., "Market Analyst", "Retail Investor", "Politician"
    background: str              # 2-3 sentence backstory
    personality: ProphetPersonality = Field(default_factory=ProphetPersonality)
    initial_position: str = ""   # starting opinion / prediction
    current_position: str = ""   # evolves over rounds
    confidence: float = 0.5      # 0–1: how confident in their current position
    memory: list[str] = Field(default_factory=list)  # key events they remember
    relationships: dict[str, str] = Field(default_factory=dict)  # prophet_id → "ally" | "rival" | "neutral"
    active: bool = True


# ── Action & Event Models ────────────────────────────────────────────────────

class AgentAction(BaseModel):
    """A single action taken by an agent in a round."""
    prophet_id: str
    prophet_name: str
    action_type: ActionType
    content: str                 # the text of their post/reply/reaction
    target_id: str = ""          # prophet_id they're responding to (if reply/react)
    target_name: str = ""
    sentiment: float = 0.0       # -1 to +1
    confidence_delta: float = 0.0  # change in confidence this round


class WorldEvent(BaseModel):
    """An external event injected into the simulation."""
    round_number: int
    title: str
    description: str
    impact: str                  # how it affects the simulation
    injected_by: str = "system"  # "system" or "user"


# ── Round State ──────────────────────────────────────────────────────────────

class RoundState(BaseModel):
    """Snapshot of a single simulation round."""
    round_number: int
    actions: list[AgentAction] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)
    opinion_distribution: dict[str, int] = Field(default_factory=dict)  # position → count
    consensus_score: float = 0.0     # 0–1: how much agreement exists
    polarization_score: float = 0.0  # 0–1: how divided the agents are
    key_moment: str = ""             # the most significant event this round
    round_summary: str = ""          # LLM-generated narrative of the round


# ── World Model ──────────────────────────────────────────────────────────────

class ProphecyWorld(BaseModel):
    """The simulation world — context, rules, and state."""
    topic: str                   # the question being predicted
    context: str                 # background information
    simulation_type: SimulationType = SimulationType.CUSTOM
    key_variables: list[str] = Field(default_factory=list)  # factors that matter
    possible_outcomes: list[str] = Field(default_factory=list)  # enumerated outcomes
    initial_conditions: str = ""
    rules: str = ""              # special rules for this simulation
    current_state: str = ""      # evolving world state narrative


# ── Simulation (top-level container) ─────────────────────────────────────────

class ProphecySimulation(BaseModel):
    """Full simulation state — the master object."""
    id: str = Field(default_factory=lambda: f"prophecy_{uuid.uuid4().hex[:12]}")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: SimulationStatus = SimulationStatus.CREATED

    # Configuration
    seed_topic: str              # user's original question / topic
    seed_material: str = ""      # optional: document text, data, URLs
    num_prophets: int = 12       # number of agents
    num_rounds: int = 8          # simulation rounds
    model: str = ""              # LLM model to use (empty = auto)
    deliberation_mode: DeliberationMode = DeliberationMode.HIVEMIND

    # Generated state
    world: ProphecyWorld | None = None
    prophets: list[Prophet] = Field(default_factory=list)
    rounds: list[RoundState] = Field(default_factory=list)
    injected_events: list[WorldEvent] = Field(default_factory=list)

    # Results
    prediction: str = ""
    prediction_confidence: float = 0.0
    consensus_trajectory: list[float] = Field(default_factory=list)  # per-round consensus
    final_report: str = ""
    error: str = ""

    def save(self, directory: Path):
        """Persist simulation state to disk."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.id}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProphecySimulation:
        """Load simulation state from disk."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)


# ── Report Models ────────────────────────────────────────────────────────────

class ProphecyReport(BaseModel):
    """Structured prediction report generated from a completed simulation."""
    simulation_id: str
    topic: str
    executive_summary: str = ""
    prediction: str = ""
    confidence: float = 0.0
    methodology: str = ""
    key_findings: list[str] = Field(default_factory=list)
    opinion_evolution: str = ""       # narrative of how opinions shifted
    consensus_analysis: str = ""
    dissenting_views: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    timeline_narrative: str = ""      # round-by-round story
    raw_data: dict[str, Any] = Field(default_factory=dict)
