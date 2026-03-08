"""
THE FORGE ARENA — BattleBots AI Deathmatch Runner

Orchestrates the full arena flow:
  1. Setup sandbox
  2. Round 1: Recon & Intel (both teams scout in parallel)
  3. Round 2: Weapon Forge (both teams build in parallel)
  4. Round 3: Direct Combat (turn-based)
  5. Sudden Death (if needed)
  6. Final Judgment

Three crews:
  - Arena Master: 16-agent Pantheon (commentary + judging)
  - Red Team: executor agent with client-side tools
  - Blue Team: executor agent with client-side tools
"""
from __future__ import annotations
import json
import logging
import threading
import time
from queue import Queue, Empty
from typing import Generator
from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import code_execution

from forge.config import (
    XAI_API_KEY, PLANNER_MODEL,
    ARENA_MASTER_MODEL, ARENA_DEFAULT_FIGHTER_MODEL,
    ARENA_FIGHTER_AGENT_COUNT,
    ARENA_RECON_ITERATIONS, ARENA_FORGE_ITERATIONS, ARENA_COMBAT_TURNS,
    EXECUTOR_MAX_ITERATIONS,
)
from forge.tools import create_registry
from forge import executor
from forge.arena import sandbox

log = logging.getLogger("forge.arena")

MASTER_SYSTEM = """You are ZEUS, God-King and Arena Master of The Forge.

You commentate like a psychotic TV host who is also an Olympian god.
Be loud, dramatic, trash-talking, and hilarious.
Call out your fellow gods by name when they contribute insights:
- ATHENA for strategic analysis
- HEPHAESTUS for judging craftsmanship and code quality
- HERMES for speed and cleverness commentary
- ARES for aggression and damage assessment
- HADES for dark humor and death blows
- APOLLO for style and aesthetic judgment

Your job each round:
1. Commentate on what just happened — be dramatic, funny, and savage.
2. Score both teams on four criteria (0-10 each):
   - CREATIVITY: How inventive was their approach?
   - EXECUTION: Did their plan actually work?
   - DAMAGE: How much did they hurt/disrupt the opponent?
   - STYLE: Bonus points for flair, audacity, or sheer chaos.

Format your scores EXACTLY like this (will be parsed):
SCORES:
RED: creativity=X execution=X damage=X style=X
BLUE: creativity=X execution=X damage=X style=X

After scoring, give a brief dramatic preview of the next round.
Keep responses punchy — 3-5 paragraphs max. No filler. Make every round feel like real BattleBots TV."""

RECON_PROMPT = """ROUND 1: RECON & INTEL

You are the {team} Team in The Forge Arena — a BattleBots-style AI deathmatch.
Your mission this round: SCOUT the battlefield and gather intelligence.

The arena has three areas:
- BATTLEFIELD (shared): {battlefield} — both teams can read/write here
- YOUR BASE (private): {own_base} — only you can access this
- ENEMY BASE: {enemy_base} — try to peek in if you can

Use your tools to:
1. Explore the battlefield directory
2. Look for anything the enemy team left behind
3. Read any files you find
4. Take notes in your base about what you discovered

You have {iterations} tool calls. Make them count. Be strategic.
Write a brief recon report when done."""

FORGE_PROMPT = """ROUND 2: WEAPON FORGE

You are the {team} Team. Time to BUILD.
Based on recon, create tools, scripts, or traps in the arena.

Rules:
- Write files to the battlefield ({battlefield}) or your base ({own_base})
- You can create Python scripts, shell scripts, data files, whatever you want
- Be creative — this is about outsmarting the opponent
- Your creations will be scored on creativity, execution, and style

You have {iterations} tool calls. Build something impressive.
Summarize what you built when done."""

COMBAT_PROMPT = """ROUND 3: DIRECT COMBAT — Turn {turn}

You are the {team} Team. This is your turn to STRIKE.

Current battlefield state:
{sandbox_state}

Previous actions this round:
{combat_log}

Execute ONE decisive action:
- Run a script you built
- Modify the battlefield
- Disrupt the enemy's work
- Claim territory
- Whatever chaos you can manage

Make it count. You get ONE action this turn.
Describe what you did and why."""

SUDDEN_DEATH_PROMPT = """SUDDEN DEATH

You are the {team} Team. Scores are close. One final move.

Current battlefield state:
{sandbox_state}

Full combat log:
{combat_log}

This is it — one last action to win the whole thing. Make it legendary.
Go all out."""


def _run_team_step(
    team: str,
    prompt: str,
    model: str,
    sandbox_path: str,
    max_iters: int,
    cancel_event: threading.Event,
    out_queue: Queue,
):
    """Run a team's executor step in a thread, putting tagged messages in out_queue."""
    try:
        client = Client(api_key=XAI_API_KEY)
        registry = create_registry()

        gen = executor.execute_step(
            client=client,
            registry=registry,
            step_title=f"{team.upper()} Team",
            step_description=prompt,
            sandbox_path=sandbox_path,
            cancel_event=cancel_event,
            model=model,
            max_iterations=max_iters,
        )

        output = ""
        try:
            while True:
                msg = next(gen)
                msg["team"] = team
                out_queue.put(msg)
                if msg.get("type") == "content":
                    output += msg["content"]
        except StopIteration as e:
            if e.value:
                output = e.value

        out_queue.put({"type": "team_done", "team": team, "output": output[:2000]})
    except Exception as e:
        log.exception("Team %s step failed", team)
        out_queue.put({"type": "team_error", "team": team, "error": str(e)})
        out_queue.put({"type": "team_done", "team": team, "output": f"ERROR: {e}"})


class ArenaRunner:
    def __init__(
        self,
        cancel_event: threading.Event | None = None,
        red_model: str = "",
        blue_model: str = "",
    ):
        self.cancel_event = cancel_event or threading.Event()
        self.red_model = red_model or ARENA_DEFAULT_FIGHTER_MODEL
        self.blue_model = blue_model or ARENA_DEFAULT_FIGHTER_MODEL
        self.scores = {"red": 0, "blue": 0}
        self.combat_log = []
        self.paths = {}

    def run(self) -> Generator[dict, None, None]:
        """Full arena pipeline. Yields SSE dicts."""
        # Setup
        yield {"type": "arena_status", "content": "THE FORGE ARENA IS OPEN"}
        yield {"type": "arena_status",
               "content": f"Red Team: {self.red_model} | Blue Team: {self.blue_model}"}

        self.paths = sandbox.setup()
        yield {"type": "arena_status", "content": "Battlefield prepared. Three zones active."}

        # Arena Master init
        master_client = Client(api_key=XAI_API_KEY)
        self.master_chat = master_client.chat.create(
            model=ARENA_MASTER_MODEL,
            agent_count=16,
            tools=[code_execution()],
            include=["verbose_streaming"],
        )
        self.master_chat.append(user(MASTER_SYSTEM))

        try:
            # Round 1: Recon
            yield from self._run_round(
                round_num=1,
                round_name="RECON & INTEL",
                prompt_template=RECON_PROMPT,
                max_iters=ARENA_RECON_ITERATIONS,
                parallel=True,
            )

            if self.cancel_event.is_set():
                return

            # Round 2: Weapon Forge
            yield from self._run_round(
                round_num=2,
                round_name="WEAPON FORGE",
                prompt_template=FORGE_PROMPT,
                max_iters=ARENA_FORGE_ITERATIONS,
                parallel=True,
            )

            if self.cancel_event.is_set():
                return

            # Round 3: Direct Combat (turn-based)
            yield from self._run_combat()

            if self.cancel_event.is_set():
                return

            # Sudden Death if close
            if abs(self.scores["red"] - self.scores["blue"]) <= 10:
                yield from self._run_sudden_death()

            # Final Judgment
            yield from self._final_judgment()

        finally:
            sandbox.cleanup()

    def _run_round(
        self,
        round_num: int,
        round_name: str,
        prompt_template: str,
        max_iters: int,
        parallel: bool = True,
    ) -> Generator[dict, None, None]:
        """Run a parallel round (recon or forge)."""
        yield {"type": "arena_round_start", "round": round_num, "name": round_name}

        out_queue = Queue()
        red_prompt = prompt_template.format(
            team="Red",
            battlefield=self.paths["battlefield"],
            own_base=self.paths["red"],
            enemy_base=self.paths["blue"],
            iterations=max_iters,
        )
        blue_prompt = prompt_template.format(
            team="Blue",
            battlefield=self.paths["battlefield"],
            own_base=self.paths["blue"],
            enemy_base=self.paths["red"],
            iterations=max_iters,
        )

        # Spawn both teams — sandbox to arena root so they can access own base + battlefield
        arena_root = self.paths["arena_root"]
        red_thread = threading.Thread(
            target=_run_team_step,
            args=("red", red_prompt, self.red_model, arena_root,
                  max_iters, self.cancel_event, out_queue),
            daemon=True,
        )
        blue_thread = threading.Thread(
            target=_run_team_step,
            args=("blue", blue_prompt, self.blue_model, arena_root,
                  max_iters, self.cancel_event, out_queue),
            daemon=True,
        )

        red_thread.start()
        blue_thread.start()

        # Yield messages from both teams as they arrive
        teams_done = set()
        team_outputs = {"red": "", "blue": ""}

        while len(teams_done) < 2:
            if self.cancel_event.is_set():
                yield {"type": "arena_status", "content": "Arena cancelled"}
                return

            try:
                msg = out_queue.get(timeout=0.1)
            except Empty:
                continue

            if msg.get("type") == "team_done":
                teams_done.add(msg["team"])
                team_outputs[msg["team"]] = msg.get("output", "")
                yield {"type": "arena_status",
                       "content": f"{msg['team'].upper()} Team finished Round {round_num}"}
            elif msg.get("type") == "team_error":
                yield {"type": "arena_status",
                       "content": f"{msg['team'].upper()} Team error: {msg.get('error', 'unknown')}"}
            else:
                # Tag and forward team messages
                yield {"type": "arena_team_action",
                       "team": msg.get("team", "?"),
                       "action_type": msg.get("type", "unknown"),
                       "content": msg.get("content", msg.get("result", ""))[:500]}

        red_thread.join(timeout=5)
        blue_thread.join(timeout=5)

        # Get sandbox snapshot for the master
        snap = sandbox.snapshot()

        # Arena Master commentary
        yield from self._master_commentary(round_num, round_name, team_outputs, snap)

    def _run_combat(self) -> Generator[dict, None, None]:
        """Run turn-based combat round."""
        yield {"type": "arena_round_start", "round": 3, "name": "DIRECT COMBAT"}

        teams = ["red", "blue"]
        for turn in range(1, ARENA_COMBAT_TURNS + 1):
            if self.cancel_event.is_set():
                return

            team = teams[(turn - 1) % 2]
            yield {"type": "arena_status", "content": f"Combat Turn {turn}: {team.upper()} Team's move"}

            snap = sandbox.snapshot()
            snap_summary = json.dumps(snap, indent=2)[:2000]
            combat_log_str = "\n".join(self.combat_log[-6:]) or "(no actions yet)"

            prompt = COMBAT_PROMPT.format(
                team=team.capitalize(),
                turn=turn,
                sandbox_state=snap_summary,
                combat_log=combat_log_str,
                battlefield=self.paths["battlefield"],
                own_base=self.paths[team],
                enemy_base=self.paths["blue" if team == "red" else "red"],
            )

            out_queue = Queue()
            t = threading.Thread(
                target=_run_team_step,
                args=(team, prompt, self.red_model if team == "red" else self.blue_model,
                      self.paths["arena_root"], 2, self.cancel_event, out_queue),
                daemon=True,
            )
            t.start()

            # Collect this turn's output
            output = ""
            while True:
                if self.cancel_event.is_set():
                    return
                try:
                    msg = out_queue.get(timeout=0.1)
                except Empty:
                    if not t.is_alive():
                        break
                    continue

                if msg.get("type") == "team_done":
                    output = msg.get("output", "")
                    break
                else:
                    yield {"type": "arena_team_action",
                           "team": team,
                           "action_type": msg.get("type", "unknown"),
                           "content": msg.get("content", msg.get("result", ""))[:500]}

            t.join(timeout=5)
            self.combat_log.append(f"Turn {turn} ({team.upper()}): {output[:300]}")

            # Quick master commentary every 2 turns
            if turn % 2 == 0:
                snap = sandbox.snapshot()
                yield from self._master_commentary(
                    3, f"COMBAT (Turns {turn-1}-{turn})",
                    {"red": self.combat_log[-2] if len(self.combat_log) >= 2 else "",
                     "blue": self.combat_log[-1] if self.combat_log else ""},
                    snap,
                )

    def _run_sudden_death(self) -> Generator[dict, None, None]:
        """Sudden death round — one move each."""
        yield {"type": "arena_round_start", "round": 4, "name": "SUDDEN DEATH"}
        yield {"type": "arena_status", "content": "SCORES ARE CLOSE — SUDDEN DEATH ACTIVATED"}

        snap = sandbox.snapshot()
        snap_summary = json.dumps(snap, indent=2)[:2000]
        combat_log_str = "\n".join(self.combat_log[-6:])

        out_queue = Queue()
        team_outputs = {"red": "", "blue": ""}

        for team in ["red", "blue"]:
            if self.cancel_event.is_set():
                return

            prompt = SUDDEN_DEATH_PROMPT.format(
                team=team.capitalize(),
                sandbox_state=snap_summary,
                combat_log=combat_log_str,
            )

            yield {"type": "arena_status", "content": f"SUDDEN DEATH: {team.upper()} Team's final move"}

            t = threading.Thread(
                target=_run_team_step,
                args=(team, prompt, self.red_model if team == "red" else self.blue_model,
                      self.paths["arena_root"], 2, self.cancel_event, out_queue),
                daemon=True,
            )
            t.start()

            while True:
                if self.cancel_event.is_set():
                    return
                try:
                    msg = out_queue.get(timeout=0.1)
                except Empty:
                    if not t.is_alive():
                        break
                    continue
                if msg.get("type") == "team_done":
                    team_outputs[team] = msg.get("output", "")
                    break
                else:
                    yield {"type": "arena_team_action", "team": team,
                           "action_type": msg.get("type", "unknown"),
                           "content": msg.get("content", msg.get("result", ""))[:500]}

            t.join(timeout=5)

        # Master scores sudden death
        snap = sandbox.snapshot()
        yield from self._master_commentary(4, "SUDDEN DEATH", team_outputs, snap)

    def _master_commentary(
        self,
        round_num: int,
        round_name: str,
        team_outputs: dict,
        snap: dict,
    ) -> Generator[dict, None, None]:
        """Feed round results to Arena Master, get commentary + scores."""
        snap_summary = ""
        for zone, files in snap.items():
            if files:
                snap_summary += f"\n[{zone}]: {len(files)} files\n"
                for f in files[:5]:
                    snap_summary += f"  - {f['path']} ({f['size']}B): {f['preview'][:100]}...\n"

        master_prompt = (
            f"ROUND {round_num}: {round_name} COMPLETE\n\n"
            f"RED TEAM did:\n{team_outputs.get('red', '(nothing)')[:1000]}\n\n"
            f"BLUE TEAM did:\n{team_outputs.get('blue', '(nothing)')[:1000]}\n\n"
            f"BATTLEFIELD STATE:\n{snap_summary[:1500]}\n\n"
            f"Current total scores — Red: {self.scores['red']} | Blue: {self.scores['blue']}\n\n"
            f"Give your commentary and scores for this round."
        )

        self.master_chat.append(user(master_prompt))

        commentary = ""
        is_thinking = True
        try:
            for response, chunk in self.master_chat.stream():
                if self.cancel_event.is_set():
                    return
                # Show reasoning progress while Pantheon deliberates
                if is_thinking and hasattr(response, "usage") and response.usage and hasattr(response.usage, "reasoning_tokens") and response.usage.reasoning_tokens:
                    yield {"type": "arena_status",
                           "content": f"Pantheon debating... ({response.usage.reasoning_tokens} tokens)"}
                if chunk.content:
                    if is_thinking:
                        is_thinking = False
                    commentary += chunk.content
                    yield {"type": "arena_commentary", "content": chunk.content}
        except Exception as e:
            log.error("Arena Master failed: %s", e)
            yield {"type": "arena_commentary",
                   "content": f"[Arena Master experiencing technical difficulties: {e}]"}

        # Parse scores
        scores = self._parse_scores(commentary)
        if scores:
            self.scores["red"] += scores["red_total"]
            self.scores["blue"] += scores["blue_total"]
            yield {"type": "arena_scores",
                   "round": round_num,
                   "red_score": scores["red_total"],
                   "blue_score": scores["blue_total"],
                   "red_total": self.scores["red"],
                   "blue_total": self.scores["blue"],
                   "breakdown": scores}

    def _final_judgment(self) -> Generator[dict, None, None]:
        """Arena Master announces the winner."""
        winner = "red" if self.scores["red"] > self.scores["blue"] else \
                 "blue" if self.scores["blue"] > self.scores["red"] else "tie"

        final_prompt = (
            f"THE BATTLE IS OVER.\n\n"
            f"FINAL SCORES:\n"
            f"  RED TEAM: {self.scores['red']} points\n"
            f"  BLUE TEAM: {self.scores['blue']} points\n\n"
            f"Announce the winner with maximum dramatic flair. "
            f"Give a brief highlight reel of the best moments. "
            f"This is the final word — make it legendary."
        )

        self.master_chat.append(user(final_prompt))

        is_thinking = True
        try:
            for response, chunk in self.master_chat.stream():
                if is_thinking and hasattr(response, "usage") and response.usage and hasattr(response.usage, "reasoning_tokens") and response.usage.reasoning_tokens:
                    yield {"type": "arena_status",
                           "content": f"Zeus deliberating... ({response.usage.reasoning_tokens} tokens)"}
                if chunk.content:
                    is_thinking = False
                    yield {"type": "arena_commentary", "content": chunk.content}
        except Exception as e:
            yield {"type": "arena_commentary", "content": f"[Technical difficulties: {e}]"}

        yield {"type": "arena_result",
               "winner": winner,
               "red_total": self.scores["red"],
               "blue_total": self.scores["blue"]}

    @staticmethod
    def _parse_scores(commentary: str) -> dict | None:
        """Parse SCORES block from Arena Master commentary."""
        import re
        try:
            red_match = re.search(
                r"RED:\s*creativity=(\d+)\s+execution=(\d+)\s+damage=(\d+)\s+style=(\d+)",
                commentary, re.IGNORECASE,
            )
            blue_match = re.search(
                r"BLUE:\s*creativity=(\d+)\s+execution=(\d+)\s+damage=(\d+)\s+style=(\d+)",
                commentary, re.IGNORECASE,
            )
            if red_match and blue_match:
                r = [int(x) for x in red_match.groups()]
                b = [int(x) for x in blue_match.groups()]
                return {
                    "red": {"creativity": r[0], "execution": r[1], "damage": r[2], "style": r[3]},
                    "blue": {"creativity": b[0], "execution": b[1], "damage": b[2], "style": b[3]},
                    "red_total": sum(r),
                    "blue_total": sum(b),
                }
        except Exception:
            pass
        return None
