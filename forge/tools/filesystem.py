from __future__ import annotations
import json
import os
from pathlib import Path
from .registry import ToolRegistry


def read_file(path: str) -> str:
    """Read and return the contents of a file."""
    p = Path(path)
    if not p.exists():
        return f'{{"error": "File not found: {path}"}}'
    if not p.is_file():
        return f'{{"error": "Not a file: {path}"}}'
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        # Cap at ~50k chars to avoid blowing context
        if len(text) > 50_000:
            text = text[:50_000] + f"\n... [truncated, {len(text)} chars total]"
        return text
    except Exception as e:
        return f'{{"error": "{e}"}}'


def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f'{{"status": "ok", "path": "{path}", "bytes": {len(content)}}}'
    except Exception as e:
        return f'{{"error": "{e}"}}'


def list_directory(path: str) -> str:
    """List files and directories at the given path."""
    p = Path(path)
    if not p.exists():
        return f'{{"error": "Path not found: {path}"}}'
    if not p.is_dir():
        return f'{{"error": "Not a directory: {path}"}}'
    try:
        entries = []
        for item in sorted(p.iterdir()):
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return json.dumps({"path": str(p), "entries": entries}, indent=2)
    except Exception as e:
        return f'{{"error": "{e}"}}'


def delete_file(path: str) -> str:
    """Delete a file (not directories)."""
    p = Path(path)
    if not p.exists():
        return f'{{"error": "File not found: {path}"}}'
    if not p.is_file():
        return json.dumps({"error": f"Not a file (refusing to delete directories): {path}"})
    try:
        p.unlink()
        return f'{{"status": "deleted", "path": "{path}"}}'
    except Exception as e:
        return f'{{"error": "{e}"}}'


# ── Registration ────────────────────────────────────────────────────────────

def register(registry: ToolRegistry):
    registry.register(
        name="read_file",
        description="Read the full contents of a text file at the given path.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
            },
            "required": ["path"],
        },
        handler=read_file,
    )
    registry.register(
        name="write_file",
        description="Write content to a file. Creates the file and parent directories if they don't exist.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to write to"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
    registry.register(
        name="list_directory",
        description="List all files and subdirectories at the given path. Returns names, types, and sizes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to directory"},
            },
            "required": ["path"],
        },
        handler=list_directory,
    )
    registry.register(
        name="delete_file",
        description="Delete a file at the given path. Cannot delete directories.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file to delete"},
            },
            "required": ["path"],
        },
        handler=delete_file,
    )
