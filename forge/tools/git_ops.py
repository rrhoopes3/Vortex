from __future__ import annotations
import json
import subprocess
from .registry import ToolRegistry
from forge.config import SHELL_WORKING_DIR, SHELL_TIMEOUT_SECONDS


def _run_git(args: list[str], cwd: str) -> dict:
    """Run a git command and return structured output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT_SECONDS,
            cwd=cwd,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[:4_000] if result.stdout else "",
            "stderr": result.stderr[:2_000] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Git command timed out after {SHELL_TIMEOUT_SECONDS}s"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def git_status(_sandbox_cwd: str = "") -> str:
    """Show the working tree status."""
    cwd = _sandbox_cwd if _sandbox_cwd else str(SHELL_WORKING_DIR)
    return json.dumps(_run_git(["status", "--short"], cwd))


def git_diff(file: str = "", staged: bool = False, _sandbox_cwd: str = "") -> str:
    """Show changes in the working tree or staging area."""
    cwd = _sandbox_cwd if _sandbox_cwd else str(SHELL_WORKING_DIR)
    args = ["diff"]
    if staged:
        args.append("--cached")
    if file:
        args.extend(["--", file])
    return json.dumps(_run_git(args, cwd))


def git_commit(message: str, _sandbox_cwd: str = "") -> str:
    """Stage all changes and commit with the given message."""
    cwd = _sandbox_cwd if _sandbox_cwd else str(SHELL_WORKING_DIR)
    # Stage all
    add_result = _run_git(["add", "-A"], cwd)
    if add_result.get("error"):
        return json.dumps(add_result)
    # Commit
    commit_result = _run_git(["commit", "-m", message], cwd)
    return json.dumps(commit_result)


def git_log(count: int = 10, _sandbox_cwd: str = "") -> str:
    """Show recent commit history."""
    cwd = _sandbox_cwd if _sandbox_cwd else str(SHELL_WORKING_DIR)
    n = max(1, min(50, count))
    return json.dumps(_run_git(
        ["log", f"--oneline", f"-{n}", "--no-color"],
        cwd,
    ))


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="git_status",
        description="Show git working tree status (short format). Returns changed/untracked files.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=git_status,
    )
    registry.register(
        name="git_diff",
        description="Show git diff of working tree changes. Use staged=true for staged changes.",
        parameters={
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Optional specific file to diff"},
                "staged": {"type": "boolean", "description": "If true, show staged (cached) changes"},
            },
        },
        handler=git_diff,
    )
    registry.register(
        name="git_commit",
        description="Stage all changes (git add -A) and commit with the given message.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
            },
            "required": ["message"],
        },
        handler=git_commit,
    )
    registry.register(
        name="git_log",
        description="Show recent git commit history (oneline format). Default: last 10 commits.",
        parameters={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of commits to show (default 10, max 50)"},
            },
        },
        handler=git_log,
    )
