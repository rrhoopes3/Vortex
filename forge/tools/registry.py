from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Callable
from xai_sdk.chat import tool as xai_tool

log = logging.getLogger("forge.tools")

# Tools with path arguments — sandbox checks apply here
# Maps tool_name → list of argument names that must be within the sandbox
_SANDBOX_PATH_ARGS = {
    "read_file": ["path"],
    "write_file": ["path"],
    "delete_file": ["path"],
    "list_directory": ["path"],
    "append_file": ["path"],
    "find_files": ["directory"],
    "grep_files": ["directory"],
    "resize_image": ["input_path", "output_path"],
    "convert_image": ["input_path", "output_path"],
    "query_sqlite": ["database"],
    "extract_archive": ["archive_path", "output_dir"],
    "zip_files": ["output_path"],
}

# Tools that should have their cwd overridden in sandbox mode
_SANDBOX_CWD_TOOLS = {"run_command", "run_python", "git_status", "git_diff", "git_commit", "git_log"}


class ToolRegistry:
    """Central registry mapping tool names → SDK definitions + handlers."""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._definitions: list = []
        self._raw_tools: list[dict] = []  # raw schemas for cross-provider conversion

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable,
    ):
        defn = xai_tool(name=name, description=description, parameters=parameters)
        self._definitions.append(defn)
        self._handlers[name] = handler
        self._raw_tools.append({"name": name, "description": description, "parameters": parameters})
        log.info("Registered tool: %s", name)

    def get_definitions(self) -> list:
        """Return list of xai_sdk tool objects to pass to chat.create()."""
        return list(self._definitions)

    def get_raw_tools(self) -> list[dict]:
        """Return raw tool schemas {name, description, parameters} for non-xAI providers."""
        return list(self._raw_tools)

    def execute(self, name: str, arguments: dict, sandbox_path: str = "") -> str:
        """Execute a tool by name with the given arguments. Returns JSON string.

        If sandbox_path is set, filesystem tools are restricted to that directory
        and run_command uses it as the working directory.
        """
        if name not in self._handlers:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # ── Sandbox enforcement ──────────────────────────────────────
        if sandbox_path:
            sandbox_root = Path(sandbox_path).resolve()

            # Check all path-based arguments
            if name in _SANDBOX_PATH_ARGS:
                for arg_name in _SANDBOX_PATH_ARGS[name]:
                    if arg_name in arguments:
                        target = Path(arguments[arg_name]).resolve()
                        if not str(target).startswith(str(sandbox_root)):
                            log.warning("Sandbox blocked %s: %s outside %s", name, target, sandbox_root)
                            return json.dumps({
                                "error": f"Sandbox: {target} is outside allowed directory {sandbox_root}",
                            })

            # Override cwd for shell/python/git commands
            if name in _SANDBOX_CWD_TOOLS:
                arguments = {**arguments, "_sandbox_cwd": str(sandbox_root)}

        # ── Execute ──────────────────────────────────────────────────
        handler = self._handlers[name]
        try:
            result = handler(**arguments)
            if isinstance(result, str):
                return result
            return json.dumps(result, default=str)
        except Exception as e:
            log.exception("Tool %s failed", name)
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

    def list_tools(self) -> list[str]:
        return list(self._handlers.keys())
