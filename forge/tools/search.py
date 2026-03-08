from __future__ import annotations
import json
import os
import re
from pathlib import Path
from .registry import ToolRegistry


def find_files(directory: str, pattern: str = "*", max_results: int = 50) -> str:
    """Find files matching a glob pattern in a directory tree."""
    p = Path(directory)
    if not p.exists():
        return json.dumps({"error": f"Directory not found: {directory}"})
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {directory}"})

    try:
        matches = []
        for match in p.rglob(pattern):
            if match.is_file():
                matches.append({
                    "path": str(match),
                    "size": match.stat().st_size,
                })
                if len(matches) >= max_results:
                    break

        return json.dumps({
            "directory": directory,
            "pattern": pattern,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "files": matches,
        }, separators=(",", ":"))
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def grep_files(directory: str, pattern: str, file_pattern: str = "*", max_results: int = 30) -> str:
    """Search file contents for a regex pattern within a directory tree."""
    p = Path(directory)
    if not p.exists():
        return json.dumps({"error": f"Directory not found: {directory}"})
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {directory}"})

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})

    results = []
    files_searched = 0
    TEXT_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
        ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh",
        ".bat", ".ps1", ".sql", ".xml", ".csv", ".env", ".gitignore",
        ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".rb",
    }

    try:
        for filepath in p.rglob(file_pattern):
            if not filepath.is_file():
                continue
            if filepath.suffix.lower() not in TEXT_EXTENSIONS and file_pattern == "*":
                continue
            files_searched += 1
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.split("\n"), 1):
                    if compiled.search(line):
                        results.append({
                            "file": str(filepath),
                            "line": i,
                            "text": line.strip()[:200],
                        })
                        if len(results) >= max_results:
                            break
            except Exception:
                continue
            if len(results) >= max_results:
                break

        return json.dumps({
            "pattern": pattern,
            "files_searched": files_searched,
            "match_count": len(results),
            "truncated": len(results) >= max_results,
            "matches": results,
        }, separators=(",", ":"))
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="find_files",
        description="Find files matching a glob pattern in a directory tree. Returns paths and sizes. Max 50 results.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search in (absolute path)"},
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py', '*.json', 'test_*' (default: '*')"},
                "max_results": {"type": "integer", "description": "Maximum results to return (default 50)"},
            },
            "required": ["directory"],
        },
        handler=find_files,
    )
    registry.register(
        name="grep_files",
        description="Search file contents for a regex pattern within a directory tree. Returns matching lines with file paths and line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search in (absolute path)"},
                "pattern": {"type": "string", "description": "Regex pattern to search for in file contents"},
                "file_pattern": {"type": "string", "description": "Glob pattern to filter files, e.g. '*.py' (default: '*' searches common text files)"},
                "max_results": {"type": "integer", "description": "Maximum matching lines to return (default 30)"},
            },
            "required": ["directory", "pattern"],
        },
        handler=grep_files,
    )
