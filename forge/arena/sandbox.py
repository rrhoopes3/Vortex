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
BATTLEFIELD = ARENA_ROOT / "battlefield"
RED_BASE = ARENA_ROOT / "red"
BLUE_BASE = ARENA_ROOT / "blue"


def setup() -> dict[str, str]:
    """Create fresh arena directories. Returns paths dict."""
    for d in [BATTLEFIELD, RED_BASE, BLUE_BASE]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # Seed the battlefield with a README so teams know the layout
    (BATTLEFIELD / "README.txt").write_text(
        "THE FORGE ARENA — BATTLEFIELD\n"
        "==============================\n"
        "Both teams can read and write files here.\n"
        "Red team private base: ../red/\n"
        "Blue team private base: ../blue/\n"
        "Fight well.\n"
    )

    return {
        "battlefield": str(BATTLEFIELD),
        "red": str(RED_BASE),
        "blue": str(BLUE_BASE),
    }


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
