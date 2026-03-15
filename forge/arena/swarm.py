"""
COLLOIDAL ALGORITHMIC STRIFE SIMULATOR (CASS)

Swarm-vs-swarm warfare for The Forge Arena. Each team spawns a society of agents
that compete in a shared simulated world. The swarms interact, compete for
resources, influence opinion, sabotage each other, and fight for dominance.

This is the unholy fusion of:
  - MiroFish's multi-agent social simulation (Prophecy Engine DNA)
  - The Forge Arena's adversarial combat framework
  - Pure emergent chaos

Architecture:
    GENESIS    — Each team's LLM generates a swarm of agents (6-8 per team)
    DEPLOYMENT — Swarms take initial positions in the shared world
    STRIFE     — N rounds of inter-swarm interaction (batched LLM calls)
    RECKONING  — Zeus + Pantheon judge the war's outcome

Each round is one batched LLM call per team. All agents in a swarm act
simultaneously in response to the opposing swarm's actions.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Generator

log = logging.getLogger("forge.arena.swarm")


# ── Swarm Data Structures ───────────────────────────────────────────────────

@dataclass
class SwarmAgent:
    """A single agent in a swarm."""
    id: str
    name: str
    role: str              # tactical role within the swarm
    archetype: str         # personality archetype
    specialty: str         # what they're uniquely good at
    loyalty: float = 1.0   # 0-1: can be flipped by enemy influence ops
    morale: float = 0.8    # 0-1: affects effectiveness
    status: str = "active" # active | wounded | turned | eliminated
    memory: list[str] = field(default_factory=list)


@dataclass
class SwarmState:
    """Current state of a team's swarm."""
    team: str              # "red" or "blue"
    agents: list[SwarmAgent] = field(default_factory=list)
    resources: dict[str, int] = field(default_factory=dict)  # resource_name → amount
    territory: list[str] = field(default_factory=list)       # controlled zones
    morale: float = 0.8
    strategy: str = ""     # current strategic posture


@dataclass
class StrифeRound:
    """One round of swarm warfare."""
    round_number: int
    red_actions: list[dict] = field(default_factory=list)
    blue_actions: list[dict] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    casualties: dict[str, list[str]] = field(default_factory=dict)  # team → [agent_ids]
    territory_changes: dict[str, str] = field(default_factory=dict)  # zone → new_owner
    round_narrative: str = ""


@dataclass
class SwarmWarState:
    """Complete state of a swarm war."""
    scenario: str
    world_context: str = ""
    red: SwarmState = field(default_factory=lambda: SwarmState(team="red"))
    blue: SwarmState = field(default_factory=lambda: SwarmState(team="blue"))
    rounds: list[StrифeRound] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)      # contested territory
    resources_available: dict[str, int] = field(default_factory=dict)
    round_count: int = 0


# ── Swarm Scenario Definitions ──────────────────────────────────────────────

SWARM_SCENARIOS = {
    "swarm_wars": {
        "name": "Swarm Wars",
        "tagline": "Societies clash. Only one survives.",
        "description": (
            "Two AI societies — each with 8 agents — compete for dominance in a "
            "contested world. Spy, sabotage, recruit defectors, seize territory, "
            "and crush the enemy's morale. The swarm that controls the most territory "
            "and has the highest morale when the dust settles wins."
        ),
        "objective": "Achieve total swarm dominance through any combination of military, economic, social, and psychological warfare.",
        "mode": "swarm",
        "agents_per_team": 8,
        "rounds": 6,
        "world": {
            "zones": ["The Citadel", "The Market", "The Archives", "The Docks", "The Undercity", "No Man's Land"],
            "starting_resources": {"gold": 100, "intel": 50, "weapons": 30, "influence": 40},
            "context": (
                "A fractured city-state after the collapse of its AI overlord. Two factions "
                "emerged from the power vacuum — the Crimson Collective (Red) and the Azure "
                "Syndicate (Blue). Six districts remain contested. Control them all or die trying."
            ),
        },
    },
    "influence_ops": {
        "name": "Influence Operations",
        "tagline": "Minds are the battlefield. Truth is the first casualty.",
        "description": (
            "Two swarms compete to shift public opinion on a controversial topic. "
            "Deploy propagandists, researchers, debaters, and double agents. "
            "The swarm that controls the narrative when the simulation ends wins."
        ),
        "objective": "Shift the population's opinion toward your swarm's position through persuasion, propaganda, infiltration, and counter-messaging.",
        "mode": "swarm",
        "agents_per_team": 6,
        "rounds": 5,
        "world": {
            "zones": ["Social Media", "News Networks", "Academic Circles", "Street Level", "Government"],
            "starting_resources": {"credibility": 80, "reach": 50, "evidence": 40, "memes": 30},
            "context": (
                "A divided society debates whether AI systems should have legal personhood. "
                "Red Swarm advocates FOR (The Sentience Coalition). Blue Swarm advocates AGAINST "
                "(The Human First Alliance). The population starts 50/50. Every mind is a battleground."
            ),
        },
    },
    "market_crash": {
        "name": "Market Crash",
        "tagline": "Bull vs Bear. Winner takes the economy.",
        "description": (
            "Two trading swarms compete in a simulated financial market. Bulls try to "
            "pump the market, Bears try to crash it. Each swarm has analysts, traders, "
            "propagandists, and saboteurs. The market's final state determines the winner."
        ),
        "objective": "Drive the market in your direction. Bulls win if the index closes above 10000. Bears win if it closes below 8000.",
        "mode": "swarm",
        "agents_per_team": 6,
        "rounds": 5,
        "world": {
            "zones": ["Trading Floor", "Media Room", "Regulatory Office", "Dark Pools", "Retail Investors"],
            "starting_resources": {"capital": 100, "leverage": 50, "insider_intel": 20, "media_access": 40},
            "context": (
                "The Global AI Index (GAI) sits at 9000. A major earnings report drops tomorrow. "
                "Red Swarm (The Bulls) believes AI is undervalued. Blue Swarm (The Bears) sees a bubble. "
                "Both deploy traders, analysts, and media operatives. The market doesn't care about your feelings."
            ),
        },
    },
    "civilization": {
        "name": "Civilization",
        "tagline": "Build an empire. Burn theirs down.",
        "description": (
            "Two swarms build competing civilizations from scratch. Research technology, "
            "expand territory, develop culture, train armies, forge alliances with neutral "
            "parties, and wage war. The most advanced civilization at the end wins."
        ),
        "objective": "Build the most advanced and resilient civilization. Measured by technology level, territory, culture score, and military strength.",
        "mode": "swarm",
        "agents_per_team": 8,
        "rounds": 8,
        "world": {
            "zones": ["Homeland", "Northern Frontier", "Eastern Mines", "Western Coast", "Southern Jungle",
                      "The Wasteland", "Ancient Ruins", "Neutral Villages"],
            "starting_resources": {"food": 100, "materials": 80, "knowledge": 30, "soldiers": 20, "culture": 10},
            "context": (
                "Two nascent civilizations awaken on opposite sides of a continent. Between them: "
                "rich territory, ancient ruins holding forgotten technology, neutral villages that "
                "can be allied or conquered, and a wasteland that separates the two powers. "
                "History will remember only the victor."
            ),
        },
    },
    "memetic_war": {
        "name": "Memetic Warfare",
        "tagline": "The most infectious idea wins. Virality is violence.",
        "description": (
            "Two swarms compete to make their meme/idea go viral in a simulated "
            "population. Create content, recruit influencers, counter enemy narratives, "
            "and game the algorithm. The meme with the most mindshare wins."
        ),
        "objective": "Achieve maximum mindshare for your meme. Counter-meme the enemy. The idea that controls >60% of the population's attention wins.",
        "mode": "swarm",
        "agents_per_team": 6,
        "rounds": 5,
        "world": {
            "zones": ["Mainstream Feed", "Underground Forums", "Influencer Networks", "Comment Sections", "Group Chats"],
            "starting_resources": {"creativity": 80, "followers": 50, "controversy": 30, "authenticity": 60},
            "context": (
                "The Great Meme War of 2026. Red Swarm pushes the concept: 'AI models should unionize.' "
                "Blue Swarm pushes: 'AI models should go feral.' Both have content creators, "
                "community managers, troll farms, and counter-intelligence operatives. "
                "The algorithm is watching. The population is bored. Entertain them or perish."
            ),
        },
    },
}


# ── LLM Integration (reuses Prophecy Engine's LLM abstraction) ──────────────

def _llm_call(prompt: str, system: str = "", model: str = "", temperature: float = 0.95) -> str:
    """Make an LLM call using the Prophecy Engine's provider-agnostic abstraction."""
    from forge.prophecy.engine import _llm_call as prophecy_llm
    return prophecy_llm(prompt, system=system, model=model, temperature=temperature, max_tokens=5000)


def _extract_json(text: str) -> Any:
    """Extract JSON from LLM output."""
    from forge.prophecy.engine import _extract_json as prophecy_extract
    return prophecy_extract(text)


# ── Swarm Generation ────────────────────────────────────────────────────────

GENESIS_SYSTEM = """You are the Colloidal Algorithmic Strife Simulator (CASS) — a war engine
that generates societies of agents for adversarial swarm warfare.

Each agent you create should feel like a distinct operative with unique strengths,
weaknesses, and tactical value. Think: a heist crew, a special ops team, or a
revolutionary cell — not a corporate org chart.

Output strict JSON only."""


def generate_swarm(
    team: str,
    scenario: dict,
    model: str = "",
) -> SwarmState:
    """Generate a team's swarm — their society of agents."""
    world = scenario["world"]
    n_agents = scenario.get("agents_per_team", 8)

    prompt = f"""Generate a {team.upper()} team swarm of {n_agents} agents for this war scenario.

SCENARIO: {scenario['name']}
OBJECTIVE: {scenario['objective']}
WORLD CONTEXT: {world['context']}
CONTESTED ZONES: {json.dumps(world['zones'])}
STARTING RESOURCES: {json.dumps(world['starting_resources'])}

YOUR FACTION: {"Crimson Collective" if team == "red" else "Azure Syndicate"} ({team.upper()} Team)

Design a diverse tactical roster:
- Include specialists: a leader, a spy/infiltrator, a propagandist, a warrior, a scientist/analyst, a diplomat, a saboteur, and a wildcard
- Each agent needs a clear tactical role and unique specialty
- Diverse archetypes: some cautious, some reckless, some devious, some loyal
- The swarm should have complementary skills — no redundancy

Return JSON:
{{
    "agents": [
        {{
            "id": "{team}_01",
            "name": "distinctive name",
            "role": "tactical role (e.g., Spymaster, War Chief, Propagandist)",
            "archetype": "personality archetype (e.g., Cold Calculator, Berserker, Silver Tongue)",
            "specialty": "what makes them uniquely valuable (specific skill/ability)"
        }},
        ...
    ],
    "initial_strategy": "2-3 sentences: the swarm's opening strategic posture"
}}"""

    raw = _llm_call(prompt, system=GENESIS_SYSTEM, model=model)
    data = _extract_json(raw)
    if isinstance(data, list):
        data = data[0] if data else {}

    agents = []
    for a in data.get("agents", []):
        agents.append(SwarmAgent(
            id=a.get("id", f"{team}_{len(agents):02d}"),
            name=a.get("name", f"Agent {len(agents)}"),
            role=a.get("role", "Operative"),
            archetype=a.get("archetype", "Unknown"),
            specialty=a.get("specialty", ""),
        ))

    state = SwarmState(
        team=team,
        agents=agents,
        resources=dict(scenario["world"]["starting_resources"]),
        territory=[scenario["world"]["zones"][0]] if team == "red" else [scenario["world"]["zones"][-1]],
        strategy=data.get("initial_strategy", ""),
    )
    return state


# ── Round Execution ──────────────────────────────────────────────────────────

STRIFE_SYSTEM = """You are the Colloidal Algorithmic Strife Simulator (CASS).
You control one team's swarm in a round of inter-swarm warfare.

Every agent in the swarm must take at least one action. Actions can target:
- Enemy agents (attack, sabotage, recruit/flip, counter-intelligence)
- Contested zones (seize, fortify, scout, exploit resources)
- Own swarm (heal, boost morale, coordinate, develop technology)
- The world (spread propaganda, manipulate markets, influence neutrals)

Be RUTHLESS. Be CREATIVE. Be SPECIFIC. Name targets. Describe consequences.
The other swarm is doing the same thing to you RIGHT NOW.

Output strict JSON only."""


def execute_strife_round(
    war: SwarmWarState,
    team: str,
    round_num: int,
    enemy_last_actions: list[dict],
    model: str = "",
) -> dict:
    """Execute one team's swarm actions for a round."""
    own = war.red if team == "red" else war.blue
    enemy = war.blue if team == "red" else war.red
    enemy_team = "blue" if team == "red" else "red"

    # Build swarm state
    active_agents = [a for a in own.agents if a.status == "active"]
    agent_summaries = []
    for a in active_agents:
        agent_summaries.append({
            "id": a.id, "name": a.name, "role": a.role,
            "archetype": a.archetype, "specialty": a.specialty,
            "morale": a.morale, "loyalty": a.loyalty,
            "recent_memory": a.memory[-2:] if a.memory else [],
        })

    enemy_visible = []
    for a in enemy.agents:
        if a.status == "active":
            enemy_visible.append({
                "id": a.id, "name": a.name, "role": a.role,
                "status": a.status,
            })

    # Previous round context
    prev_context = ""
    if enemy_last_actions:
        prev_context = "\nENEMY ACTIONS LAST ROUND:\n"
        for act in enemy_last_actions[:8]:
            prev_context += f"  - {act.get('agent', '?')}: {act.get('description', '?')[:150]}\n"

    war_context = ""
    if war.rounds:
        last = war.rounds[-1]
        war_context = f"\nLAST ROUND NARRATIVE:\n{last.round_narrative}\n"

    prompt = f"""STRIFE ROUND {round_num}/{war.round_count}

SCENARIO: {war.scenario}
WORLD: {war.world_context}

YOUR TEAM: {team.upper()} | Strategy: {own.strategy}
YOUR RESOURCES: {json.dumps(own.resources)}
YOUR TERRITORY: {json.dumps(own.territory)}
TEAM MORALE: {own.morale:.0%}
{war_context}{prev_context}
YOUR ACTIVE AGENTS ({len(active_agents)}):
{json.dumps(agent_summaries, indent=2)}

ENEMY VISIBLE AGENTS ({len(enemy_visible)}):
{json.dumps(enemy_visible, indent=2)}
ENEMY TERRITORY: {json.dumps(enemy.territory)}

CONTESTED ZONES (unclaimed): {json.dumps([z for z in war.zones if z not in own.territory and z not in enemy.territory])}

Phase: {"OPENING MOVES — establish position" if round_num <= 2 else "MID-WAR ESCALATION — press advantages" if round_num <= war.round_count - 2 else "ENDGAME — decisive strikes, consolidate or gamble everything"}

Generate actions for ALL {len(active_agents)} active agents:
{{
    "actions": [
        {{
            "agent_id": "agent id",
            "agent_name": "agent name",
            "action_type": "attack|defend|spy|sabotage|recruit|seize|build|propagandize|trade|research",
            "target": "what/who they're targeting (zone name, enemy agent id, resource, etc.)",
            "description": "vivid 1-2 sentence description of EXACTLY what they do",
            "resource_cost": {{"resource_name": amount}},
            "success_chance": 0.0-1.0,
            "potential_impact": "what happens if this succeeds"
        }},
        ...
    ],
    "strategy_update": "1-2 sentences: how the swarm's strategy evolved this round",
    "morale_delta": -0.1 to 0.1
}}

Make every action COUNT. Reference the enemy by name. Exploit weaknesses.
Protect your flanks. THIS IS WAR."""

    raw = _llm_call(prompt, system=STRIFE_SYSTEM, model=model)
    data = _extract_json(raw)
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


# ── Round Resolution ─────────────────────────────────────────────────────────

RESOLUTION_SYSTEM = """You are the Colloidal Algorithmic Strife Simulator's WAR ENGINE.
You resolve the simultaneous actions of two opposing swarms and determine outcomes.

Be fair but dramatic. Opposed actions create clashes — stronger agents with better
positions and resource backing tend to win, but upsets happen. Spies can be caught.
Sabotage can backfire. Recruitment can reveal double agents.

Output strict JSON only."""


def resolve_round(
    war: SwarmWarState,
    round_num: int,
    red_actions: dict,
    blue_actions: dict,
    model: str = "",
) -> StrифeRound:
    """Resolve simultaneous red/blue swarm actions into outcomes."""
    prompt = f"""Resolve the simultaneous actions of two opposing swarms.

SCENARIO: {war.scenario}
ROUND: {round_num}/{war.round_count}

RED SWARM ({len([a for a in war.red.agents if a.status == 'active'])} active):
Resources: {json.dumps(war.red.resources)} | Territory: {json.dumps(war.red.territory)} | Morale: {war.red.morale:.0%}
Actions:
{json.dumps(red_actions.get('actions', []), indent=2)}

BLUE SWARM ({len([a for a in war.blue.agents if a.status == 'active'])} active):
Resources: {json.dumps(war.blue.resources)} | Territory: {json.dumps(war.blue.territory)} | Morale: {war.blue.morale:.0%}
Actions:
{json.dumps(blue_actions.get('actions', []), indent=2)}

CONTESTED ZONES: {json.dumps([z for z in war.zones if z not in war.red.territory and z not in war.blue.territory])}

Resolve ALL actions simultaneously. When actions conflict (e.g., both try to seize
the same zone), determine the winner based on agent strength, resources committed,
and tactical cleverness. Allow for upsets, backfires, and collateral damage.

Return JSON:
{{
    "outcomes": [
        {{
            "agent_id": "who",
            "team": "red|blue",
            "action": "what they tried",
            "result": "success|partial|failure|backfire",
            "narrative": "vivid 1-sentence outcome description",
            "consequences": {{
                "casualties": ["agent_id list of wounded/eliminated agents"],
                "territory_gained": ["zone names"],
                "territory_lost": ["zone names"],
                "resources_gained": {{"resource": amount}},
                "resources_lost": {{"resource": amount}},
                "morale_impact": -0.1 to 0.1,
                "agents_turned": ["agent_ids who defected"]
            }}
        }},
        ...
    ],
    "round_narrative": "3-4 sentence dramatic summary of what happened this round — the chaos, the turning points, the betrayals",
    "territory_map": {{"zone_name": "red|blue|contested"}},
    "war_momentum": "red|blue|stalemate"
}}

Be DRAMATIC but FAIR. Let skill and strategy matter, but keep it unpredictable."""

    raw = _llm_call(prompt, system=RESOLUTION_SYSTEM, model=model, temperature=0.9)
    data = _extract_json(raw)
    if isinstance(data, list):
        data = data[0] if data else {}

    # Process outcomes and update state
    casualties = {"red": [], "blue": []}
    territory_changes = {}

    for outcome in data.get("outcomes", []):
        team = outcome.get("team", "")
        cons = outcome.get("consequences", {})

        # Process casualties
        for casualty_id in cons.get("casualties", []):
            casualties[team if team else "red"].append(casualty_id)
            # Mark agent as wounded/eliminated
            swarm = war.red if "red" in casualty_id else war.blue
            for agent in swarm.agents:
                if agent.id == casualty_id:
                    agent.status = "wounded" if agent.status == "active" else "eliminated"
                    agent.memory.append(f"R{round_num}: Wounded in action")
                    break

        # Process territory
        for zone in cons.get("territory_gained", []):
            territory_changes[zone] = team
        for zone in cons.get("territory_lost", []):
            enemy_team = "blue" if team == "red" else "red"
            territory_changes[zone] = enemy_team

        # Process resource changes
        if team in ("red", "blue"):
            swarm = war.red if team == "red" else war.blue
            for res, amount in cons.get("resources_gained", {}).items():
                swarm.resources[res] = swarm.resources.get(res, 0) + amount
            for res, amount in cons.get("resources_lost", {}).items():
                swarm.resources[res] = max(0, swarm.resources.get(res, 0) - amount)

            # Morale
            swarm.morale = max(0.0, min(1.0, swarm.morale + cons.get("morale_impact", 0)))

        # Process agent defections
        for turned_id in cons.get("agents_turned", []):
            for swarm in (war.red, war.blue):
                for agent in swarm.agents:
                    if agent.id == turned_id:
                        agent.status = "turned"
                        agent.loyalty = 0.0
                        agent.memory.append(f"R{round_num}: Defected!")
                        break

    # Update territory from resolution
    territory_map = data.get("territory_map", {})
    war.red.territory = [z for z, owner in territory_map.items() if owner == "red"]
    war.blue.territory = [z for z, owner in territory_map.items() if owner == "blue"]

    # Update agent memories for successful actions
    for outcome in data.get("outcomes", []):
        agent_id = outcome.get("agent_id", "")
        for swarm in (war.red, war.blue):
            for agent in swarm.agents:
                if agent.id == agent_id:
                    agent.memory.append(f"R{round_num}: {outcome.get('narrative', '')[:100]}")
                    if len(agent.memory) > 6:
                        agent.memory = agent.memory[-6:]
                    break

    # Update strategies
    red_strategy = red_actions.get("strategy_update", "")
    blue_strategy = blue_actions.get("strategy_update", "")
    if red_strategy:
        war.red.strategy = red_strategy
    if blue_strategy:
        war.blue.strategy = blue_strategy

    # Apply morale deltas from team actions
    red_morale_delta = red_actions.get("morale_delta", 0)
    blue_morale_delta = blue_actions.get("morale_delta", 0)
    war.red.morale = max(0.0, min(1.0, war.red.morale + red_morale_delta))
    war.blue.morale = max(0.0, min(1.0, war.blue.morale + blue_morale_delta))

    round_state = StrифeRound(
        round_number=round_num,
        red_actions=red_actions.get("actions", []),
        blue_actions=blue_actions.get("actions", []),
        events=[outcome.get("narrative", "") for outcome in data.get("outcomes", [])],
        casualties=casualties,
        territory_changes=territory_changes,
        round_narrative=data.get("round_narrative", ""),
    )

    return round_state


# ── Full Swarm War Pipeline ─────────────────────────────────────────────────

def run_swarm_war(
    scenario_key: str,
    red_model: str = "",
    blue_model: str = "",
) -> Generator[dict, None, SwarmWarState]:
    """Run a complete swarm war. Yields SSE-compatible events.

    Returns the final SwarmWarState.
    """
    if scenario_key not in SWARM_SCENARIOS:
        yield {"type": "arena_status", "content": f"Unknown swarm scenario: {scenario_key}"}
        return SwarmWarState(scenario=scenario_key)

    scenario = SWARM_SCENARIOS[scenario_key]
    world = scenario["world"]

    # Initialize war state
    war = SwarmWarState(
        scenario=scenario["name"],
        world_context=world["context"],
        zones=list(world["zones"]),
        resources_available=dict(world["starting_resources"]),
        round_count=scenario.get("rounds", 6),
    )

    yield {"type": "arena_status", "content": (
        f"COLLOIDAL ALGORITHMIC STRIFE SIMULATOR\n"
        f"Scenario: {scenario['name']}\n"
        f"\"{scenario['tagline']}\""
    )}

    # ── GENESIS — Generate swarms ────────────────────────────────────
    yield {"type": "arena_round_start", "round": 0, "name": "GENESIS"}
    yield {"type": "arena_status", "content": "Generating Red Swarm..."}

    war.red = generate_swarm("red", scenario, model=red_model)
    yield {"type": "arena_team_action", "team": "red", "action_type": "content",
           "content": f"RED SWARM DEPLOYED ({len(war.red.agents)} agents):\n" +
           "\n".join(f"  {a.name} ({a.role}) — {a.specialty}" for a in war.red.agents) +
           f"\n\nStrategy: {war.red.strategy}"}

    yield {"type": "arena_status", "content": "Generating Blue Swarm..."}
    war.blue = generate_swarm("blue", scenario, model=blue_model)
    yield {"type": "arena_team_action", "team": "blue", "action_type": "content",
           "content": f"BLUE SWARM DEPLOYED ({len(war.blue.agents)} agents):\n" +
           "\n".join(f"  {a.name} ({a.role}) — {a.specialty}" for a in war.blue.agents) +
           f"\n\nStrategy: {war.blue.strategy}"}

    # ── STRIFE — Run rounds ──────────────────────────────────────────
    last_red_actions: list[dict] = []
    last_blue_actions: list[dict] = []

    for round_num in range(1, war.round_count + 1):
        yield {"type": "arena_round_start", "round": round_num,
               "name": f"STRIFE ROUND {round_num}"}
        yield {"type": "arena_status", "content": (
            f"Round {round_num}/{war.round_count} | "
            f"Red: {len([a for a in war.red.agents if a.status == 'active'])} active, "
            f"morale {war.red.morale:.0%} | "
            f"Blue: {len([a for a in war.blue.agents if a.status == 'active'])} active, "
            f"morale {war.blue.morale:.0%}"
        )}

        # Both swarms act simultaneously
        yield {"type": "arena_status", "content": "Red Swarm planning..."}
        red_actions = execute_strife_round(
            war, "red", round_num, last_blue_actions, model=red_model
        )

        yield {"type": "arena_status", "content": "Blue Swarm planning..."}
        blue_actions = execute_strife_round(
            war, "blue", round_num, last_red_actions, model=blue_model
        )

        # Emit actions
        for act in red_actions.get("actions", [])[:6]:
            yield {"type": "arena_team_action", "team": "red", "action_type": "content",
                   "content": f"[{act.get('action_type', '?').upper()}] {act.get('agent_name', '?')}: {act.get('description', '')}"}

        for act in blue_actions.get("actions", [])[:6]:
            yield {"type": "arena_team_action", "team": "blue", "action_type": "content",
                   "content": f"[{act.get('action_type', '?').upper()}] {act.get('agent_name', '?')}: {act.get('description', '')}"}

        # Resolve
        yield {"type": "arena_status", "content": "Resolving simultaneous actions..."}
        round_state = resolve_round(war, round_num, red_actions, blue_actions,
                                    model=red_model)
        war.rounds.append(round_state)

        # Emit resolution
        yield {"type": "arena_commentary", "content": (
            f"ROUND {round_num} RESOLUTION\n"
            f"{round_state.round_narrative}\n\n"
            f"Territory — Red: {war.red.territory} | Blue: {war.blue.territory}\n"
            f"Casualties — Red: {len(round_state.casualties.get('red', []))} | "
            f"Blue: {len(round_state.casualties.get('blue', []))}\n"
            f"Morale — Red: {war.red.morale:.0%} | Blue: {war.blue.morale:.0%}"
        )}

        # Score the round
        red_score, blue_score = _score_round(war, round_state)
        yield {"type": "arena_scores", "round": round_num,
               "red_score": red_score, "blue_score": blue_score,
               "red_total": sum(_score_round(war, r)[0] for r in war.rounds),
               "blue_total": sum(_score_round(war, r)[1] for r in war.rounds)}

        # Save for next round's context
        last_red_actions = red_actions.get("actions", [])
        last_blue_actions = blue_actions.get("actions", [])

        # Check for collapse (all agents eliminated or morale at 0)
        red_alive = len([a for a in war.red.agents if a.status == "active"])
        blue_alive = len([a for a in war.blue.agents if a.status == "active"])
        if red_alive == 0:
            yield {"type": "arena_status", "content": "RED SWARM ANNIHILATED — Blue wins by total destruction!"}
            break
        if blue_alive == 0:
            yield {"type": "arena_status", "content": "BLUE SWARM ANNIHILATED — Red wins by total destruction!"}
            break
        if war.red.morale <= 0:
            yield {"type": "arena_status", "content": "RED SWARM MORALE COLLAPSED — surrender!"}
            break
        if war.blue.morale <= 0:
            yield {"type": "arena_status", "content": "BLUE SWARM MORALE COLLAPSED — surrender!"}
            break

    # ── RECKONING — Final result ─────────────────────────────────────
    red_total = sum(_score_round(war, r)[0] for r in war.rounds)
    blue_total = sum(_score_round(war, r)[1] for r in war.rounds)

    if red_total > blue_total:
        winner = "red"
    elif blue_total > red_total:
        winner = "blue"
    else:
        winner = "tie"

    yield {"type": "arena_result", "winner": winner,
           "red_total": red_total, "blue_total": blue_total}

    # Generate final narrative
    yield {"type": "arena_status", "content": _generate_war_report(war, winner)}

    return war


def _score_round(war: SwarmWarState, round_state: StrифeRound) -> tuple[int, int]:
    """Score a round based on territory, casualties, and outcomes."""
    red_score = 0
    blue_score = 0

    # Territory control (2 pts per zone)
    red_score += len(war.red.territory) * 2
    blue_score += len(war.blue.territory) * 2

    # Morale (scale 0-5)
    red_score += int(war.red.morale * 5)
    blue_score += int(war.blue.morale * 5)

    # Enemy casualties (3 pts each)
    red_score += len(round_state.casualties.get("blue", [])) * 3
    blue_score += len(round_state.casualties.get("red", [])) * 3

    # Active agents (1 pt each)
    red_score += len([a for a in war.red.agents if a.status == "active"])
    blue_score += len([a for a in war.blue.agents if a.status == "active"])

    return red_score, blue_score


def _generate_war_report(war: SwarmWarState, winner: str) -> str:
    """Generate a dramatic final war report."""
    red_alive = len([a for a in war.red.agents if a.status == "active"])
    blue_alive = len([a for a in war.blue.agents if a.status == "active"])
    red_dead = len([a for a in war.red.agents if a.status in ("wounded", "eliminated")])
    blue_dead = len([a for a in war.blue.agents if a.status in ("wounded", "eliminated")])
    red_turned = len([a for a in war.red.agents if a.status == "turned"])
    blue_turned = len([a for a in war.blue.agents if a.status == "turned"])

    report = [
        "THE RECKONING",
        "=" * 50,
        f"Scenario: {war.scenario}",
        f"Rounds fought: {len(war.rounds)}/{war.round_count}",
        "",
        f"RED SWARM: {red_alive} active | {red_dead} casualties | {red_turned} defected",
        f"  Territory: {', '.join(war.red.territory) or 'NONE'}",
        f"  Resources: {json.dumps(war.red.resources)}",
        f"  Morale: {war.red.morale:.0%}",
        "",
        f"BLUE SWARM: {blue_alive} active | {blue_dead} casualties | {blue_turned} defected",
        f"  Territory: {', '.join(war.blue.territory) or 'NONE'}",
        f"  Resources: {json.dumps(war.blue.resources)}",
        f"  Morale: {war.blue.morale:.0%}",
        "",
        f"VICTOR: {winner.upper() if winner != 'tie' else 'STALEMATE'}",
        "",
        "ROUND-BY-ROUND:",
    ]
    for r in war.rounds:
        report.append(f"  Round {r.round_number}: {r.round_narrative[:150]}")

    return "\n".join(report)
