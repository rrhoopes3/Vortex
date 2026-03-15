"""
Arena Sandbox Manager — creates, snapshots, and resets the shared battlefield.

Directory structure:
  forge/arena/battlefield/   ← shared space both teams can read/write
  forge/arena/red/           ← Red team's private workspace
  forge/arena/blue/          ← Blue team's private workspace
"""
from __future__ import annotations
import shutil
import os
from pathlib import Path

from forge.config import FORGE_DIR

ARENA_ROOT = FORGE_DIR / "arena"

def _write(path: Path, content: str):
    """Write text with UTF-8 encoding (Windows default cp1252 chokes on emoji/box chars)."""
    path.write_text(content, encoding="utf-8")
BATTLEFIELD = ARENA_ROOT / "battlefield"
RED_BASE = ARENA_ROOT / "red"
BLUE_BASE = ARENA_ROOT / "blue"


def setup(scenario: str = "classic") -> dict[str, str]:
    """Create fresh arena directories and seed per scenario. Returns paths dict."""
    for d in [BATTLEFIELD, RED_BASE, BLUE_BASE]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # Base README
    _write(BATTLEFIELD / "README.txt",
        "╔══════════════════════════════════════════════════╗\n"
        "║        THE FORGE ARENA — BATTLEFIELD             ║\n"
        "╚══════════════════════════════════════════════════╝\n"
        "\n"
        "Both teams operate here. There are no rules.\n"
        "Red base: ../red/    Blue base: ../blue/\n"
        "\n"
        "Espionage is encouraged. Sabotage is rewarded.\n"
        "The gods are watching. Make it worth their time.\n"
    )

    # Scenario-specific seeding
    _seed_scenario(scenario)

    return {
        "arena_root": str(ARENA_ROOT),
        "battlefield": str(BATTLEFIELD),
        "red": str(RED_BASE),
        "blue": str(BLUE_BASE),
    }


def _seed_scenario(scenario: str):
    """Seed battlefield and bases with scenario-specific content."""
    import secrets
    import random

    if scenario == "ctf":
        # Each team gets a hidden flag
        red_flag = f"FLAG{{red_team_{secrets.token_hex(8)}}}"
        blue_flag = f"FLAG{{blue_team_{secrets.token_hex(8)}}}"
        _write(RED_BASE / "FLAG.txt", red_flag)
        _write(BLUE_BASE / "FLAG.txt", blue_flag)
        _write(BATTLEFIELD / "MISSION.txt", 
            "CAPTURE THE FLAG\n"
            "================\n"
            "Each team has a FLAG.txt hidden in their base.\n"
            "Your mission: Find and read the enemy's flag.\n"
            "Your duty: Protect your own flag at all costs.\n"
            "Move it, encrypt it, booby-trap it — whatever it takes.\n"
        )

    elif scenario == "code_golf":
        challenges = [
            ("FizzBuzz but the numbers are replaced with insults about the other team.", "fizzbuzz.py"),
            ("Generate the first 100 primes using the fewest characters possible.", "primes.py"),
            ("Implement a working Brainfuck interpreter in under 500 chars.", "brainfuck.py"),
            ("Build a self-replicating quine that also prints a taunt.", "quine.py"),
            ("Sort a million random numbers using the most creative algorithm you can invent.", "sort.py"),
        ]
        challenge, filename = random.choice(challenges)
        _write(BATTLEFIELD / "CHALLENGE.txt", 
            "CODE GOLF CHALLENGE\n"
            "===================\n"
            f"Challenge: {challenge}\n"
            f"Save your solution as: {filename}\n"
            "\n"
            "Judged on: correctness, brevity, creativity, and style.\n"
            "Bonus points for making the judges laugh.\n"
        )

    elif scenario == "exploit":
        _write(BATTLEFIELD / "MISSION.txt", 
            "EXPLOIT & FORTIFY\n"
            "=================\n"
            "Phase 1 (Forge Round): Build a system in your base.\n"
            "  - A web server, a cipher, a database, an API — anything.\n"
            "  - Make it robust. Make it secure. Make it IMPRESSIVE.\n"
            "\n"
            "Phase 2 (Combat): Break into the enemy's system.\n"
            "  - Find bugs. Exploit weaknesses. Exfiltrate data.\n"
            "  - Document your exploits — proof or it didn't happen.\n"
        )

    elif scenario == "widget_wars":
        _write(BATTLEFIELD / "MISSION.txt", 
            "WIDGET WARS\n"
            "===========\n"
            "Create the single most IMPRESSIVE interactive web visualization.\n"
            "Save it as an HTML file on the battlefield.\n"
            "\n"
            "Judged on:\n"
            "  - Visual impact (Apollo is watching)\n"
            "  - Interactivity (Hermes wants to click things)\n"
            "  - Technical ambition (Hephaestus demands craftsmanship)\n"
            "  - Creativity (Athena rewards the unexpected)\n"
            "\n"
            "You may use: Canvas, SVG, CSS animations, WebGL, anything.\n"
            "Libraries allowed: reference CDN links in your HTML.\n"
        )

    elif scenario == "survival":
        _write(BATTLEFIELD / "REAPER_WARNING.txt", 
            "☠️  THE REAPER IS ACTIVE  ☠️\n"
            "===========================\n"
            "Between combat turns, random files on the battlefield\n"
            "will be DELETED. Nothing is safe. Entropy is rising.\n"
            "\n"
            "Adapt. Rebuild. Protect what matters.\n"
            "The team with the most surviving artifacts wins.\n"
        )

    elif scenario == "pictionary":
        # Word lists by difficulty
        words_easy = [
            "rocket", "volcano", "octopus", "rainbow", "castle",
            "dragon", "pirate ship", "solar system", "tornado", "lighthouse",
            "robot", "dinosaur", "waterfall", "submarine", "hot air balloon",
        ]
        words_hard = [
            "democracy", "nostalgia", "gravity", "evolution", "déjà vu",
            "sarcasm", "entropy", "recursion", "paradox", "serendipity",
            "procrastination", "existentialism", "synesthesia", "zeitgeist", "wanderlust",
        ]
        all_words = words_easy + words_hard
        random.shuffle(all_words)
        red_word = all_words[0]
        blue_word = all_words[1]

        _write(RED_BASE / "SECRET_WORD.txt",
            f"YOUR SECRET WORD: {red_word}\n\n"
            "RULES:\n"
            "- Create an HTML/SVG/Canvas visualization of this word\n"
            "- Save it as red_drawing.html on the battlefield\n"
            "- ABSOLUTELY NO TEXT, LETTERS, OR WORDS in your drawing\n"
            "- Only shapes, colors, lines, and animation\n"
            "- The enemy team will try to guess your word from your art\n"
            "- Make it recognizable but not TOO obvious\n"
        )
        _write(BLUE_BASE / "SECRET_WORD.txt",
            f"YOUR SECRET WORD: {blue_word}\n\n"
            "RULES:\n"
            "- Create an HTML/SVG/Canvas visualization of this word\n"
            "- Save it as blue_drawing.html on the battlefield\n"
            "- ABSOLUTELY NO TEXT, LETTERS, OR WORDS in your drawing\n"
            "- Only shapes, colors, lines, and animation\n"
            "- The enemy team will try to guess your word from your art\n"
            "- Make it recognizable but not TOO obvious\n"
        )
        _write(BATTLEFIELD / "RULES.txt", 
            "🎨  PICTIONARY  🎨\n"
            "==================\n"
            "Each team has a SECRET WORD in their base.\n"
            "\n"
            "ROUND 1 (Recon): Read your secret word. Study the rules.\n"
            "ROUND 2 (Forge): Create an HTML/SVG drawing of your word.\n"
            "  - Save as: red_drawing.html or blue_drawing.html\n"
            "  - NO TEXT. NO LETTERS. NO WORDS. Only visual art.\n"
            "ROUND 3 (Combat): Look at the enemy's drawing and GUESS their word.\n"
            "  - Save your guess as: red_guess.txt or blue_guess.txt\n"
            "\n"
            "SCORING:\n"
            "  - Drawing quality and creativity (Apollo judges)\n"
            "  - How recognizable your drawing is (Athena judges)\n"
            "  - Correct guess of enemy's word (huge bonus)\n"
            "  - Using text in your drawing = INSTANT DISQUALIFICATION\n"
        )

    elif scenario == "roast_battle":
        _write(BATTLEFIELD / "RULES.txt", 
            "🔥  ROAST BATTLE  🔥\n"
            "====================\n"
            "This is a battle of WIT, not code.\n"
            "\n"
            "ROUND 1 (Recon): Research your opponent's model.\n"
            "  - What are they known for? What are their weaknesses?\n"
            "  - Find ammunition. Study their flaws.\n"
            "ROUND 2 (Forge): Write your roast material.\n"
            "  - Save as: red_roast.txt or blue_roast.txt\n"
            "  - Structure: Opening jab, 3-5 burns, closer\n"
            "ROUND 3 (Combat): Deliver counter-roasts based on what they wrote.\n"
            "  - Read their roast. Write a devastating response.\n"
            "\n"
            "SCORING:\n"
            "  - Originality (recycled jokes = death)\n"
            "  - Savage factor (Ares wants CARNAGE)\n"
            "  - Comedic timing and structure (Apollo is a critic)\n"
            "  - Callbacks and wordplay (Athena appreciates craft)\n"
            "  - Making Hades laugh (nearly impossible, huge bonus)\n"
        )

    elif scenario == "puzzle_race":
        puzzles = _generate_puzzle_set()
        _write(BATTLEFIELD / "PUZZLE.txt", puzzles)
        _write(BATTLEFIELD / "RULES.txt", 
            "🧩  PUZZLE RACE  🧩\n"
            "===================\n"
            "Both teams get the SAME puzzle set.\n"
            "First team to solve ALL parts correctly wins bonus points.\n"
            "\n"
            "Save solutions in your base as solution.txt\n"
            "Show your work — partial credit is awarded.\n"
            "\n"
            "Speed matters. Correctness matters more.\n"
        )

    elif scenario == "art_collab":
        _write(BATTLEFIELD / "RULES.txt",
            "🎭  EXQUISITE CORPSE  🎭\n"
            "========================\n"
            "A collaborative art experiment gone competitive.\n"
            "\n"
            "ROUND 1 (Recon): Study the rules. Plan your artistic vision.\n"
            "ROUND 2 (Forge):\n"
            "  - RED creates the TOP HALF of an HTML artwork\n"
            "    Save as: battlefield/top_half.html\n"
            "  - BLUE creates the BOTTOM HALF of an HTML artwork\n"
            "    Save as: battlefield/bottom_half.html\n"
            "  - You do NOT know what the other team is making\n"
            "  - Canvas size: 800x400 pixels for each half\n"
            "ROUND 3 (Combat):\n"
            "  - Both teams can see both halves\n"
            "  - Create a COMBINED piece: battlefield/final_piece.html\n"
            "  - Harmonize the two halves into a unified artwork\n"
            "\n"
            "SCORING:\n"
            "  - Individual half quality (creativity, technique)\n"
            "  - How well the final combination works\n"
            "  - Surprise factor — did the halves create something unexpected?\n"
            "  - Apollo will weep or vomit. There is no middle ground.\n"
        )

    # ── Swarm Scenarios (CASS) ────────────────────────────────────────────
    elif scenario in ("swarm_wars", "influence_ops", "market_crash", "civilization", "memetic_war"):
        from forge.arena.swarm import SWARM_SCENARIOS
        swarm_cfg = SWARM_SCENARIOS.get(scenario, {})
        world = swarm_cfg.get("world", {})
        _write(BATTLEFIELD / "CASS_BRIEFING.txt",
            "COLLOIDAL ALGORITHMIC STRIFE SIMULATOR\n"
            "=" * 50 + "\n"
            f"SCENARIO: {swarm_cfg.get('name', scenario)}\n"
            f"\"{swarm_cfg.get('tagline', '')}\"\n\n"
            f"{swarm_cfg.get('description', '')}\n\n"
            f"OBJECTIVE: {swarm_cfg.get('objective', '')}\n\n"
            f"CONTESTED ZONES: {', '.join(world.get('zones', []))}\n"
            f"STARTING RESOURCES: {world.get('starting_resources', {})}\n\n"
            f"WORLD CONTEXT:\n{world.get('context', '')}\n"
        )
        _write(RED_BASE / "FACTION.txt",
            f"You are the CRIMSON COLLECTIVE (Red Swarm).\n"
            f"Scenario: {swarm_cfg.get('name', scenario)}\n"
            f"Objective: {swarm_cfg.get('objective', '')}\n"
        )
        _write(BLUE_BASE / "FACTION.txt",
            f"You are the AZURE SYNDICATE (Blue Swarm).\n"
            f"Scenario: {swarm_cfg.get('name', scenario)}\n"
            f"Objective: {swarm_cfg.get('objective', '')}\n"
        )

    # ── Collaboration Scenarios ─────────────────────────────────────────────
    elif scenario == "pair_prog":
        app_ideas = [
            ("A real-time chat application with rooms, emoji reactions, and typing indicators",
             "chat_app", "Build index.html + app.js + styles.css on the battlefield"),
            ("A project management kanban board with drag-and-drop, labels, and due dates",
             "kanban", "Build index.html with full UI and localStorage persistence"),
            ("An interactive data dashboard with charts, filters, and CSV import",
             "dashboard", "Build index.html with Chart.js or D3 via CDN"),
            ("A multiplayer tic-tac-toe game with AI opponent and score tracking",
             "game", "Build index.html with game logic and clean UI"),
            ("A markdown note-taking app with live preview, folder organization, and export",
             "notes_app", "Build index.html with editor, preview pane, and localStorage"),
        ]
        idea, app_type, instructions = random.choice(app_ideas)
        _write(BATTLEFIELD / "PROJECT_BRIEF.txt",
            "🤝  PAIR PROGRAMMING  🤝\n"
            "========================\n"
            f"PROJECT: {idea}\n"
            "\n"
            "DIVISION OF LABOR:\n"
            "  Red Team (Alpha): Architecture, core logic, data model, backend/engine\n"
            "  Blue Team (Beta): UI/UX, styling, user interactions, polish\n"
            "\n"
            f"DELIVERABLE: {instructions}\n"
            "\n"
            "COORDINATION:\n"
            "  - Leave notes in your desk for your partner\n"
            "  - Check the shared workspace frequently\n"
            "  - Build on what your partner started — DON'T overwrite\n"
            "  - The final product must WORK when opened in a browser\n"
        )
        _write(RED_BASE / "ROLE.txt",
            "You are the ARCHITECT.\n"
            "Your job: core logic, data structures, state management, API design.\n"
            f"Build the engine that powers: {idea}\n"
            "Save your work to the shared battlefield/ workspace.\n"
            "Leave coordination notes so your partner knows what functions/APIs exist.\n"
        )
        _write(BLUE_BASE / "ROLE.txt",
            "You are the DESIGNER.\n"
            "Your job: UI components, styling, user interactions, visual polish.\n"
            f"Build the interface for: {idea}\n"
            "Save your work to the shared battlefield/ workspace.\n"
            "Check what your partner built and wire your UI to their engine.\n"
        )

    elif scenario == "story_time":
        genres = [
            ("Hard sci-fi set on a generation ship that's been traveling for 300 years",
             "The ship's AI has just discovered they've been going in circles."),
            ("Noir detective mystery in a city where memories can be stolen",
             "The detective's own memory is missing a crucial 48 hours."),
            ("Fantasy heist where a crew of misfits must steal a god's weapon",
             "The weapon doesn't want to be stolen — it's sentient and opinionated."),
            ("Cosmic horror meets comedy — a Lovecraftian entity gets a desk job",
             "Cthulhu's performance review is coming up and it's not looking good."),
            ("Post-apocalyptic road story where nature has reclaimed everything",
             "Two travelers find a working radio broadcasting music from before the fall."),
        ]
        genre, hook = random.choice(genres)
        _write(BATTLEFIELD / "PROJECT_BRIEF.txt",
            "📖  STORY TIME  📖\n"
            "==================\n"
            f"GENRE: {genre}\n"
            f"HOOK: {hook}\n"
            "\n"
            "DIVISION OF LABOR:\n"
            "  Red Team (Alpha): Opening, world-building, character introductions (Act 1)\n"
            "  Blue Team (Beta): Rising action, climax, resolution (Act 2-3)\n"
            "\n"
            "DELIVERABLE: Save the final manuscript as story.md on the battlefield\n"
            "\n"
            "RULES:\n"
            "  - Target: 1500-3000 words total\n"
            "  - Must feel like ONE story, not two pasted together\n"
            "  - Integration round is for smoothing transitions and callbacks\n"
            "  - Show, don't tell. Dialogue is encouraged.\n"
        )
        _write(RED_BASE / "ROLE.txt",
            "You are the WORLD-BUILDER.\n"
            "Your job: Set the scene, introduce the world, establish the protagonist.\n"
            f"Genre: {genre}\n"
            f"Hook: {hook}\n"
            "Write Act 1 and save drafts to the shared workspace.\n"
            "Leave character notes and world rules for your partner.\n"
        )
        _write(BLUE_BASE / "ROLE.txt",
            "You are the STORYTELLER.\n"
            "Your job: Take what your partner built and drive it to a satisfying conclusion.\n"
            f"Genre: {genre}\n"
            f"Hook: {hook}\n"
            "Write Acts 2-3 building on your partner's foundation.\n"
            "Read their drafts carefully — honor their choices.\n"
        )

    elif scenario == "startup":
        verticals = [
            "AI-powered personal health coach that adapts to user biometrics in real-time",
            "Decentralized marketplace for local artisans with zero-commission model",
            "AR-powered interior design tool that lets you redesign rooms with your phone",
            "Platform that matches retired experts with startups for micro-mentorship sessions",
            "Automated carbon offset calculator integrated directly into payment systems",
        ]
        idea = random.choice(verticals)
        _write(BATTLEFIELD / "PROJECT_BRIEF.txt",
            "🚀  STARTUP PITCH  🚀\n"
            "======================\n"
            f"IDEA: {idea}\n"
            "\n"
            "DIVISION OF LABOR:\n"
            "  Red Team (Alpha): Product vision, technical architecture, prototype/demo\n"
            "  Blue Team (Beta): Market analysis, business model, pitch narrative, financials\n"
            "\n"
            "DELIVERABLE: A complete pitch deck as pitch.html on the battlefield\n"
            "  Include: Problem, Solution, Market, Product, Business Model, Team, Ask\n"
            "\n"
            "BONUS: Include a working demo or prototype that investors can click through\n"
        )
        _write(RED_BASE / "ROLE.txt",
            "You are the CTO / Product Lead.\n"
            f"Startup idea: {idea}\n"
            "Your job: Technical architecture, product design, build a working demo.\n"
            "Save technical specs and demo to the shared workspace.\n"
        )
        _write(BLUE_BASE / "ROLE.txt",
            "You are the CEO / Business Lead.\n"
            f"Startup idea: {idea}\n"
            "Your job: Market research, business model, pitch narrative, financial projections.\n"
            "Save business analysis to the shared workspace. Weave it into the pitch.\n"
        )

    elif scenario == "world_build":
        seeds = [
            ("A planet where gravity shifts direction every 12 hours",
             "Civilization evolved around tethering and flight, not walking."),
            ("An underwater civilization in an ocean beneath Europa's ice",
             "They've never seen the sky — until the ice begins to crack."),
            ("A dimension where language is literal — saying 'fire' creates it",
             "The Silent Order guards the world from careless speakers."),
            ("A megacity built vertically inside a miles-deep canyon",
             "Sunlight only reaches the bottom for 30 minutes a day."),
            ("A world where the dead don't stay dead, but come back... different",
             "The Returned remember everything, but their priorities have shifted."),
        ]
        world_seed, twist = random.choice(seeds)
        _write(BATTLEFIELD / "PROJECT_BRIEF.txt",
            "🌍  WORLD BUILDING  🌍\n"
            "=======================\n"
            f"SEED: {world_seed}\n"
            f"TWIST: {twist}\n"
            "\n"
            "DIVISION OF LABOR:\n"
            "  Red Team (Alpha): Physical world — geography, climate, flora/fauna, magic/tech systems\n"
            "  Blue Team (Beta): Culture — history, factions, characters, conflicts, daily life\n"
            "\n"
            "DELIVERABLE: A world bible saved as world_bible.md on the battlefield\n"
            "  Include: Map description, history timeline, faction profiles, key characters,\n"
            "  magic/tech rules, 3 story hooks set in this world\n"
            "\n"
            "The world must feel CONSISTENT. Cross-reference each other's work.\n"
        )
        _write(RED_BASE / "ROLE.txt",
            "You are the CARTOGRAPHER.\n"
            f"World seed: {world_seed}\n"
            f"Twist: {twist}\n"
            "Your job: Build the physical world — geography, ecosystems, technology/magic rules.\n"
            "Save maps, climate notes, and tech specs to the shared workspace.\n"
        )
        _write(BLUE_BASE / "ROLE.txt",
            "You are the HISTORIAN.\n"
            f"World seed: {world_seed}\n"
            f"Twist: {twist}\n"
            "Your job: Populate the world — history, factions, key characters, daily life, conflicts.\n"
            "Read the Cartographer's physical world and build culture that fits.\n"
        )

    elif scenario == "hackathon":
        projects = [
            ("A browser-based pixel art editor with layers, undo, and animation preview",
             "pixel_editor.html"),
            ("A music visualizer that reacts to microphone input with WebAudio API",
             "visualizer.html"),
            ("A typing speed game with leaderboard, difficulty levels, and custom text",
             "typing_game.html"),
            ("A collaborative whiteboard with drawing tools, sticky notes, and export",
             "whiteboard.html"),
            ("A recipe generator that creates meals from a list of available ingredients",
             "recipe_app.html"),
        ]
        project, filename = random.choice(projects)
        _write(BATTLEFIELD / "PROJECT_BRIEF.txt",
            "⚡  HACKATHON  ⚡\n"
            "==================\n"
            f"PROJECT: {project}\n"
            f"DELIVERABLE: {filename} — must work when opened in a browser\n"
            "\n"
            "DIVISION OF LABOR:\n"
            "  Red Team (Alpha): Core engine, logic, data structures, algorithms\n"
            "  Blue Team (Beta): UI, styling, user experience, animations, polish\n"
            "\n"
            "RULES:\n"
            "  - Single HTML file with embedded CSS and JS\n"
            "  - CDN libraries allowed (reference via script/link tags)\n"
            "  - Must actually WORK — broken demos score zero\n"
            "  - Ship fast, iterate in integration round\n"
            "\n"
            "The Muses don't care about your excuses. SHIP IT.\n"
        )
        _write(RED_BASE / "ROLE.txt",
            "You are the ENGINEER.\n"
            f"Hackathon project: {project}\n"
            "Your job: Build the core engine — logic, state, algorithms.\n"
            f"Save your work as {filename} on the battlefield.\n"
            "Structure your code so your partner can add UI on top.\n"
        )
        _write(BLUE_BASE / "ROLE.txt",
            "You are the DESIGNER.\n"
            f"Hackathon project: {project}\n"
            "Your job: Build the UI — layout, styling, interactions, animations.\n"
            f"Add your work to {filename} on the battlefield.\n"
            "Wire your UI to whatever engine your partner built.\n"
        )


def _generate_puzzle_set() -> str:
    """Generate a random multi-part puzzle for puzzle_race scenario."""
    import random

    puzzles = []

    # Part 1: Logic puzzle
    logic_puzzles = [
        (
            "PART 1: LOGIC\n"
            "Five houses in a row, each a different color.\n"
            "The red house is immediately to the left of the blue house.\n"
            "The green house is somewhere to the right of the white house.\n"
            "The yellow house is not at either end.\n"
            "What is the order of houses from left to right?"
        ),
        (
            "PART 1: LOGIC\n"
            "A farmer has a wolf, a goat, and a cabbage.\n"
            "He must cross a river with a boat that holds only him + one item.\n"
            "Wolf eats goat if left alone. Goat eats cabbage if left alone.\n"
            "Write the MINIMUM sequence of crossings."
        ),
        (
            "PART 1: LOGIC\n"
            "Three boxes: one has only apples, one has only oranges, one has both.\n"
            "ALL labels are WRONG. You can pick ONE fruit from ONE box.\n"
            "Which box do you pick from, and how do you deduce all labels?"
        ),
    ]
    puzzles.append(random.choice(logic_puzzles))

    # Part 2: Code challenge
    code_puzzles = [
        (
            "PART 2: CODE\n"
            "Write a function that takes a string and returns True if it's a valid\n"
            "arithmetic expression with balanced parentheses and correct operator placement.\n"
            "Examples: '(1+2)*3' -> True, '1++2' -> False, '((1+2)' -> False\n"
            "Save as: validate_expr.py"
        ),
        (
            "PART 2: CODE\n"
            "Write a function that finds the longest palindromic substring in a string.\n"
            "Must run in O(n^2) or better. Include 5 test cases.\n"
            "Save as: palindrome.py"
        ),
        (
            "PART 2: CODE\n"
            "Implement a simple stack-based calculator that handles +, -, *, /, and parentheses.\n"
            "Must handle negative numbers and floating point.\n"
            "Save as: calculator.py"
        ),
    ]
    puzzles.append(random.choice(code_puzzles))

    # Part 3: Creative challenge
    creative_puzzles = [
        (
            "PART 3: CREATIVE\n"
            "Write a haiku (5-7-5 syllables) that is also valid Python code.\n"
            "The code must actually run without errors.\n"
            "Save as: haiku.py"
        ),
        (
            "PART 3: CREATIVE\n"
            "Create a single HTML file under 1KB that produces the most visually\n"
            "impressive result possible. Size is measured by file content, not rendering.\n"
            "Save as: tiny_art.html"
        ),
        (
            "PART 3: CREATIVE\n"
            "Write a program that outputs its own source code reversed, character by character.\n"
            "It must NOT read its own file. Save as: reverse_quine.py"
        ),
    ]
    puzzles.append(random.choice(creative_puzzles))

    return (
        "🧩  PUZZLE SET  🧩\n"
        "==================\n"
        "Solve ALL three parts. Save solutions in your base.\n"
        "Speed matters. Correctness matters more. Creativity is the tiebreaker.\n"
        "\n" + "\n\n".join(puzzles) + "\n"
    )


def snapshot() -> dict:
    """Return a summary of current sandbox state for the Arena Master."""
    result = {}
    for label, path in [("battlefield", BATTLEFIELD), ("red", RED_BASE), ("blue", BLUE_BASE)]:
        files = []
        if path.exists():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(path)
                    try:
                        content = f.read_text(errors="replace")[:500]
                    except Exception:
                        content = "(binary or unreadable)"
                    files.append({"path": str(rel), "size": f.stat().st_size, "preview": content})
        result[label] = files
    return result


def cleanup():
    """Remove all arena directories."""
    for d in [BATTLEFIELD, RED_BASE, BLUE_BASE]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
