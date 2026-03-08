from __future__ import annotations
import subprocess
import json
from .registry import ToolRegistry
from forge.config import SHELL_TIMEOUT_SECONDS, SHELL_WORKING_DIR


def run_command(command: str) -> str:
    """Run a shell command and return stdout + stderr."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT_SECONDS,
            cwd=str(SHELL_WORKING_DIR),
        )
        output = {
            "returncode": result.returncode,
            "stdout": result.stdout[:10_000] if result.stdout else "",
            "stderr": result.stderr[:5_000] if result.stderr else "",
        }
        return json.dumps(output)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {SHELL_TIMEOUT_SECONDS}s", "command": command})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ── Registration ────────────────────────────────────────────────────────────

def register(registry: ToolRegistry):
    registry.register(
        name="run_command",
        description=(
            "Run a shell command and return its output. "
            f"Commands execute in {SHELL_WORKING_DIR} with a {SHELL_TIMEOUT_SECONDS}s timeout. "
            "Use for: git operations, pip install, running scripts, file operations, etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        },
        handler=run_command,
    )
