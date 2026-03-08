from __future__ import annotations
import json
from pathlib import Path
from .registry import ToolRegistry


def resize_image(input_path: str, output_path: str, width: int, height: int = 0) -> str:
    """Resize an image to the specified dimensions."""
    try:
        from PIL import Image
    except ImportError:
        return json.dumps({"error": "Pillow not installed. Run: pip install Pillow"})

    p = Path(input_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {input_path}"})

    try:
        img = Image.open(input_path)
        orig_w, orig_h = img.size

        if height <= 0:
            # Maintain aspect ratio
            ratio = width / orig_w
            height = int(orig_h * ratio)

        img_resized = img.resize((width, height), Image.LANCZOS)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        img_resized.save(output_path)

        return json.dumps({
            "status": "ok",
            "input": input_path,
            "output": output_path,
            "original_size": f"{orig_w}x{orig_h}",
            "new_size": f"{width}x{height}",
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def convert_image(input_path: str, output_path: str, format: str = "") -> str:
    """Convert an image to a different format (determined by output extension or format param)."""
    try:
        from PIL import Image
    except ImportError:
        return json.dumps({"error": "Pillow not installed. Run: pip install Pillow"})

    p = Path(input_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {input_path}"})

    try:
        img = Image.open(input_path)

        # Determine format from output extension or explicit param
        fmt = format.upper() if format else None
        if not fmt:
            ext = Path(output_path).suffix.lower()
            fmt_map = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
                       ".gif": "GIF", ".bmp": "BMP", ".webp": "WEBP", ".tiff": "TIFF"}
            fmt = fmt_map.get(ext)
            if not fmt:
                return json.dumps({"error": f"Cannot determine format from extension: {ext}"})

        # Handle RGBA → RGB for JPEG
        if fmt == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format=fmt)

        return json.dumps({
            "status": "ok",
            "input": input_path,
            "output": output_path,
            "format": fmt,
            "size": out.stat().st_size,
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="resize_image",
        description="Resize an image. If only width is given, height is calculated to maintain aspect ratio. Requires Pillow.",
        parameters={
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to the source image"},
                "output_path": {"type": "string", "description": "Path to save the resized image"},
                "width": {"type": "integer", "description": "Target width in pixels"},
                "height": {"type": "integer", "description": "Target height in pixels (0 = auto from aspect ratio)"},
            },
            "required": ["input_path", "output_path", "width"],
        },
        handler=resize_image,
    )
    registry.register(
        name="convert_image",
        description="Convert an image to a different format (PNG, JPEG, GIF, BMP, WEBP). Format is inferred from the output file extension. Requires Pillow.",
        parameters={
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Path to the source image"},
                "output_path": {"type": "string", "description": "Path to save the converted image (extension determines format)"},
                "format": {"type": "string", "description": "Explicit format override (PNG, JPEG, etc.)"},
            },
            "required": ["input_path", "output_path"],
        },
        handler=convert_image,
    )
