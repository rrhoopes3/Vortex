from __future__ import annotations
import json
import subprocess
import sys
from .registry import ToolRegistry


def copy_to_clipboard(text: str) -> str:
    """Copy text to the system clipboard."""
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(
                ["clip"], stdin=subprocess.PIPE, shell=True
            )
            process.communicate(text.encode("utf-16-le"))
        elif sys.platform == "darwin":
            process = subprocess.Popen(
                ["pbcopy"], stdin=subprocess.PIPE
            )
            process.communicate(text.encode("utf-8"))
        else:
            # Linux — try xclip, then xsel
            try:
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                )
                process.communicate(text.encode("utf-8"))
            except FileNotFoundError:
                process = subprocess.Popen(
                    ["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE
                )
                process.communicate(text.encode("utf-8"))

        return json.dumps({"status": "ok", "chars": len(text)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def read_clipboard() -> str:
    """Read text from the system clipboard."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            content = result.stdout
        elif sys.platform == "darwin":
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=5
            )
            content = result.stdout
        else:
            try:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True, text=True, timeout=5
                )
                content = result.stdout
            except FileNotFoundError:
                result = subprocess.run(
                    ["xsel", "--clipboard", "--output"],
                    capture_output=True, text=True, timeout=5
                )
                content = result.stdout

        return json.dumps({
            "content": content[:4_000] if content else "",
            "chars": len(content) if content else 0,
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="copy_to_clipboard",
        description="Copy text to the system clipboard.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy to clipboard"},
            },
            "required": ["text"],
        },
        handler=copy_to_clipboard,
    )
    registry.register(
        name="read_clipboard",
        description="Read the current contents of the system clipboard.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=read_clipboard,
    )
