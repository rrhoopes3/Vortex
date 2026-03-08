from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Callable
from xai_sdk.chat import tool as xai_tool

log = logging.getLogger("forge.tools")

# Tools that accept a "path" argument — sandbox checks apply here
_PATH_ARG_TOOLS = {"read_file", "write_file", "delete_file", "list_directory"}


class ToolRegistry:
    """Central registry mapping tool names → SDK definitions + handlers."""

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._definitions: list = []

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
        log.info("Registered tool: %s", name)

    def get_definitions(self) -> list:
        """Return list of xai_sdk tool objects to pass to chat.create()."""
        return list(self._definitions)

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

            # Check path-based tools
            if name in _PATH_ARG_TOOLS and "path" in arguments:
                target = Path(arguments["path"]).resolve()
                if not str(target).startswith(str(sandbox_root)):
                    log.warning("Sandbox blocked %s: %s outside %s", name, target, sandbox_root)
                    return json.dumps({
                        "error": f"Sandbox: {target} is outside allowed directory {sandbox_root}",
                    })

            # Override cwd for shell commands
            if name == "run_command":
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
