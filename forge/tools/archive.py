from __future__ import annotations
import json
import zipfile
import tarfile
import os
from pathlib import Path
from .registry import ToolRegistry


def zip_files(output_path: str, files: str) -> str:
    """Create a ZIP archive from a list of file/directory paths.

    Args:
        output_path: path for the .zip file
        files: JSON array of paths to include, e.g. '["file1.py", "dir/"]'
    """
    try:
        paths = json.loads(files)
        if not isinstance(paths, list) or not paths:
            return json.dumps({"error": "files must be a non-empty JSON array of paths"})
    except json.JSONDecodeError:
        return json.dumps({"error": "files must be a valid JSON array"})

    try:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        added = []

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in paths:
                p = Path(file_path)
                if not p.exists():
                    return json.dumps({"error": f"File not found: {file_path}"})
                if p.is_file():
                    zf.write(p, p.name)
                    added.append(p.name)
                elif p.is_dir():
                    for root, dirs, fnames in os.walk(p):
                        for fname in fnames:
                            full = Path(root) / fname
                            arcname = str(full.relative_to(p.parent))
                            zf.write(full, arcname)
                            added.append(arcname)

        return json.dumps({
            "status": "ok",
            "output": output_path,
            "files_added": len(added),
            "size": out.stat().st_size,
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def extract_archive(archive_path: str, output_dir: str) -> str:
    """Extract a ZIP or TAR archive to a directory."""
    p = Path(archive_path)
    if not p.exists():
        return json.dumps({"error": f"Archive not found: {archive_path}"})

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        extracted = []
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Security: check for path traversal
                for name in zf.namelist():
                    target = (out / name).resolve()
                    if not str(target).startswith(str(out.resolve())):
                        return json.dumps({"error": f"Zip slip detected: {name}"})
                zf.extractall(output_dir)
                extracted = zf.namelist()
        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as tf:
                # Security: check for path traversal
                for member in tf.getmembers():
                    target = (out / member.name).resolve()
                    if not str(target).startswith(str(out.resolve())):
                        return json.dumps({"error": f"Path traversal detected: {member.name}"})
                tf.extractall(output_dir)
                extracted = tf.getnames()
        else:
            return json.dumps({"error": "Unsupported archive format (only ZIP and TAR supported)"})

        return json.dumps({
            "status": "ok",
            "archive": archive_path,
            "output_dir": output_dir,
            "files_extracted": len(extracted),
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="zip_files",
        description="Create a ZIP archive from a list of files or directories.",
        parameters={
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "Path for the output .zip file"},
                "files": {"type": "string", "description": "JSON array of file/directory paths to include, e.g. '[\"file1.py\", \"src/\"]'"},
            },
            "required": ["output_path", "files"],
        },
        handler=zip_files,
    )
    registry.register(
        name="extract_archive",
        description="Extract a ZIP or TAR (.tar, .tar.gz, .tgz) archive to a directory.",
        parameters={
            "type": "object",
            "properties": {
                "archive_path": {"type": "string", "description": "Path to the archive file"},
                "output_dir": {"type": "string", "description": "Directory to extract files into"},
            },
            "required": ["archive_path", "output_dir"],
        },
        handler=extract_archive,
    )
