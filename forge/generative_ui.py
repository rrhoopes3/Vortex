"""
Generative UI — interactive widget rendering for The Forge.

Inspired by pi-generative-ui (github.com/Michaelliv/pi-generative-ui),
adapted for web-based SSE streaming instead of native macOS windows.

The executor can call `render_widget` to emit interactive HTML/SVG/JS widgets
that render live in the Forge console inside sandboxed iframes. Widgets support:
  - Progressive rendering (HTML chunks streamed as tokens arrive)
  - CDN libraries: Chart.js, D3.js, Three.js, Mermaid
  - Bidirectional messaging (widget ↔ agent via postMessage)
  - Design guidelines for chart, diagram, interactive, and art widgets

Architecture:
  Widget tool call → executor yields {"type": "widget_*"} SSE events
  → frontend renders in sandboxed <iframe srcdoc="..."> with morphdom diffing
  → widget postMessage("forge:widget_event", ...) bubbles back as tool results
"""
from __future__ import annotations
import json
import logging
import hashlib
import time
from typing import Any

log = logging.getLogger("forge.generative_ui")

# ── CDN Libraries ────────────────────────────────────────────────────────────

CDN_LIBS = {
    "chart.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
    "d3": "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js",
    "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.min.js",
    "mermaid": "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js",
    "morphdom": "https://cdn.jsdelivr.net/npm/morphdom@2.7.4/dist/morphdom-umd.min.js",
    "plotly": "https://cdn.jsdelivr.net/npm/plotly.js-dist@2/plotly.min.js",
    "katex": "https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.js",
    "katex-css": "https://cdn.jsdelivr.net/npm/katex@0.16/dist/katex.min.css",
}

# ── Widget Types ─────────────────────────────────────────────────────────────

WIDGET_TYPES = {
    "chart": "Interactive chart (line, bar, pie, scatter, etc.)",
    "diagram": "Flowchart, sequence diagram, state machine, architecture diagram",
    "dashboard": "Multi-metric dashboard with live data",
    "interactive": "Custom interactive widget with controls (sliders, buttons, inputs)",
    "visualization": "Data visualization (heatmap, treemap, network graph, etc.)",
    "3d": "3D scene rendered with Three.js",
    "art": "Generative/algorithmic art piece",
    "table": "Interactive data table with sorting and filtering",
    "form": "Interactive form that sends data back to the agent",
    "custom": "Freeform HTML/CSS/JS widget",
}

# ── Design Guidelines ────────────────────────────────────────────────────────
# Compact guidelines extracted from claude.ai's generative UI system,
# adapted for The Forge's dark theme.

DESIGN_GUIDELINES = """
## Forge Widget Design Guidelines

### Color Palette (matches Forge dark theme)
- Background: #0b0e12, #121821, #171f2a
- Text: #edf2f7 (primary), #9cacbf (muted)
- Accent: #f2a74b (amber), #ffbe67 (amber bright)
- Signal: #63c7b2 (teal/success)
- Warning: #f5c35b (yellow)
- Danger: #ff7b7b (red)
- Blue: #74b7ff
- Borders: rgba(255,255,255,0.08)

### Typography
- Font: system-ui, -apple-system, sans-serif
- Monospace: 'Cascadia Code', 'Consolas', monospace
- Base size: 14px, scale with rem

### Layout Rules
- Use CSS Grid or Flexbox, never absolute positioning for layout
- Responsive: widget must work from 300px to 1200px wide
- Padding: 16px minimum
- Border-radius: 10-14px for containers, 6-8px for controls
- Use subtle borders: 1px solid rgba(255,255,255,0.08)

### Charts (Chart.js)
- Always set responsive: true, maintainAspectRatio: false
- Dark theme: grid color rgba(255,255,255,0.06), tick color #9cacbf
- Use the accent palette for data series: #f2a74b, #63c7b2, #74b7ff, #ff7b7b, #f5c35b
- Include legends when >1 series
- Animate on load (default Chart.js animation is fine)

### Interactive Controls
- Sliders: accent-color: #f2a74b
- Buttons: background rgba(242,167,75,0.15), border 1px solid rgba(242,167,75,0.3)
- Inputs: background rgba(9,13,19,0.88), border-radius 8px
- Hover states: subtle background shift, never jarring

### 3D (Three.js)
- Transparent background (alpha: true) to blend with Forge theme
- Orbit controls for interactivity
- Ambient + directional lighting minimum

### Diagrams (Mermaid)
- Use dark theme: %%{init: {'theme': 'dark'}}%%
- Prefer flowchart LR or TD

### Animation
- Prefer CSS transitions (0.2s ease) over JS animation
- requestAnimationFrame for continuous animation
- Respect prefers-reduced-motion

### Accessibility
- All interactive elements must be keyboard-accessible
- Use semantic HTML (button, input, label)
- Sufficient color contrast (4.5:1 minimum)
"""

# ── Widget HTML Scaffold ─────────────────────────────────────────────────────

def build_widget_html(
    widget_type: str,
    title: str,
    html_content: str,
    css: str = "",
    js: str = "",
    libraries: list[str] | None = None,
    width: str = "100%",
    height: str = "400px",
    widget_id: str = "",
) -> str:
    """Build a complete, self-contained HTML document for a widget iframe.

    Returns the full HTML string to be used as iframe srcdoc.
    """
    lib_tags = []
    for lib in (libraries or []):
        lib_lower = lib.lower().strip()
        # Try exact match, then without .js suffix, then with .js suffix
        candidates = [lib_lower, lib_lower.replace(".js", ""), lib_lower + ".js"]
        matched_key = None
        for candidate in candidates:
            if candidate in CDN_LIBS:
                matched_key = candidate
                break
        if not matched_key:
            continue
        # Special case: katex needs both CSS and JS
        if matched_key == "katex":
            lib_tags.append(f'<link rel="stylesheet" href="{CDN_LIBS["katex-css"]}">')
            lib_tags.append(f'<script src="{CDN_LIBS["katex"]}"></script>')
        else:
            url = CDN_LIBS[matched_key]
            if url.endswith(".css"):
                lib_tags.append(f'<link rel="stylesheet" href="{url}">')
            else:
                lib_tags.append(f'<script src="{url}"></script>')

    lib_html = "\n    ".join(lib_tags)

    if not widget_id:
        widget_id = hashlib.md5(f"{title}-{time.time()}".encode()).hexdigest()[:8]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {lib_html}
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: transparent;
            color: #edf2f7;
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            padding: 16px;
            overflow-x: hidden;
        }}
        /* Forge dark theme base tokens */
        :root {{
            --bg: #0b0e12;
            --bg-elevated: #121821;
            --bg-panel: #171f2a;
            --text: #edf2f7;
            --muted: #9cacbf;
            --accent: #f2a74b;
            --accent-bright: #ffbe67;
            --signal: #63c7b2;
            --warning: #f5c35b;
            --danger: #ff7b7b;
            --blue: #74b7ff;
            --border: rgba(255,255,255,0.08);
            --border-strong: rgba(255,255,255,0.16);
        }}
        .widget-title {{
            font-size: 0.85rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--accent-bright);
            margin-bottom: 12px;
        }}
        .widget-container {{
            width: 100%;
            min-height: 100px;
        }}
        button {{
            font: inherit;
            cursor: pointer;
            padding: 6px 14px;
            border-radius: 8px;
            border: 1px solid rgba(242,167,75,0.3);
            background: rgba(242,167,75,0.15);
            color: var(--accent-bright);
            transition: background 0.2s ease, transform 0.15s ease;
        }}
        button:hover {{
            background: rgba(242,167,75,0.25);
            transform: translateY(-1px);
        }}
        input[type="range"] {{ accent-color: var(--accent); }}
        input[type="text"], input[type="number"], select, textarea {{
            font: inherit;
            padding: 6px 10px;
            border-radius: 8px;
            border: 1px solid var(--border-strong);
            background: rgba(9,13,19,0.88);
            color: var(--text);
            outline: none;
        }}
        input:focus, select:focus, textarea:focus {{
            border-color: rgba(242,167,75,0.5);
        }}
        label {{
            color: var(--muted);
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        /* Custom scrollbar */
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-thumb {{ border-radius: 999px; background: rgba(255,255,255,0.12); }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        /* Widget-specific CSS */
        {css}
    </style>
</head>
<body>
    <div class="widget-title">{title}</div>
    <div class="widget-container" id="widget-root">
        {html_content}
    </div>
    <script>
        // Forge widget bridge — bidirectional messaging
        const ForgeWidget = {{
            id: "{widget_id}",
            send(eventName, data) {{
                window.parent.postMessage({{
                    source: "forge-widget",
                    widgetId: this.id,
                    event: eventName,
                    data: data,
                }}, "*");
            }},
            onMessage(callback) {{
                window.addEventListener("message", (e) => {{
                    if (e.data && e.data.source === "forge-host" && e.data.widgetId === this.id) {{
                        callback(e.data.event, e.data.data);
                    }}
                }});
            }},
        }};
        // Widget JavaScript
        {js}
    </script>
</body>
</html>"""


# ── Tool Handler ─────────────────────────────────────────────────────────────

def handle_render_widget(
    widget_type: str = "custom",
    title: str = "Widget",
    html: str = "",
    css: str = "",
    js: str = "",
    libraries: list[str] | None = None,
    width: str = "100%",
    height: str = "400px",
    description: str = "",
) -> dict[str, Any]:
    """Tool handler for render_widget. Returns the widget payload for SSE emission.

    The executor yields this as a {"type": "widget_render"} SSE message.
    The tool result returned to the LLM is a confirmation string.
    """
    if widget_type not in WIDGET_TYPES:
        return {"error": f"Unknown widget type: {widget_type}. Valid: {', '.join(WIDGET_TYPES.keys())}"}

    widget_id = hashlib.md5(f"{title}-{time.time()}".encode()).hexdigest()[:8]

    full_html = build_widget_html(
        widget_type=widget_type,
        title=title,
        html_content=html,
        css=css,
        js=js,
        libraries=libraries,
        width=width,
        height=height,
        widget_id=widget_id,
    )

    return {
        "_widget": True,
        "widget_id": widget_id,
        "widget_type": widget_type,
        "title": title,
        "description": description or f"{widget_type} widget: {title}",
        "html": full_html,
        "width": width,
        "height": height,
    }


# ── Tool Registration ────────────────────────────────────────────────────────

RENDER_WIDGET_SCHEMA = {
    "type": "object",
    "properties": {
        "widget_type": {
            "type": "string",
            "enum": list(WIDGET_TYPES.keys()),
            "description": "Type of widget to render. Options: " + ", ".join(
                f"{k} ({v})" for k, v in WIDGET_TYPES.items()
            ),
        },
        "title": {
            "type": "string",
            "description": "Display title for the widget header.",
        },
        "html": {
            "type": "string",
            "description": "The HTML content for the widget body. Can include any valid HTML elements.",
        },
        "css": {
            "type": "string",
            "description": "Additional CSS styles scoped to this widget. Base dark-theme tokens (--accent, --signal, --bg, etc.) are pre-defined.",
        },
        "js": {
            "type": "string",
            "description": (
                "JavaScript to execute after the widget loads. "
                "Has access to ForgeWidget.send(event, data) for messaging back to the agent, "
                "and ForgeWidget.onMessage(callback) for receiving messages. "
                "CDN libraries (Chart.js, D3, Three.js, Mermaid, Plotly, KaTeX) are available if listed in 'libraries'."
            ),
        },
        "libraries": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"CDN libraries to include. Available: {', '.join(CDN_LIBS.keys())}",
        },
        "width": {
            "type": "string",
            "description": "CSS width for the widget iframe. Default: '100%'.",
        },
        "height": {
            "type": "string",
            "description": "CSS height for the widget iframe. Default: '400px'. Use taller for 3D/charts.",
        },
        "description": {
            "type": "string",
            "description": "Brief description of what this widget shows (for accessibility and logging).",
        },
    },
    "required": ["widget_type", "title", "html"],
}


def register_widget_tools(registry):
    """Register generative UI tools with the tool registry."""

    def _render_widget(**kwargs):
        result = handle_render_widget(**kwargs)
        if "error" in result:
            return json.dumps(result)
        # The actual widget rendering happens via SSE side-channel.
        # Return a JSON result that includes the _widget flag for the executor
        # to intercept and emit as a widget SSE event.
        return json.dumps(result, default=str)

    registry.register(
        name="render_widget",
        description=(
            "Render an interactive HTML widget in the Forge console. "
            "Use this to create visualizations, charts, dashboards, interactive controls, "
            "3D scenes, diagrams, and custom UI components. "
            "The widget renders in a sandboxed iframe with a dark theme matching The Forge. "
            "Available CDN libraries: Chart.js, D3.js, Three.js, Mermaid, Plotly, KaTeX. "
            "Use ForgeWidget.send(event, data) in JS to send data back to the agent.\n\n"
            + DESIGN_GUIDELINES
        ),
        parameters=RENDER_WIDGET_SCHEMA,
        handler=_render_widget,
    )
    log.info("Registered generative UI tools")


# ── Widget Result Interception ───────────────────────────────────────────────

def intercept_widget_result(result: str) -> tuple[dict | None, str]:
    """Check if a tool result contains a widget payload.

    Returns (widget_event, llm_result):
      - widget_event: dict to yield as SSE if this is a widget, else None
      - llm_result: the string to feed back to the LLM as the tool result
    """
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None, result

    if not isinstance(parsed, dict) or not parsed.get("_widget"):
        return None, result

    # Build the SSE event for the frontend
    widget_event = {
        "type": "widget_render",
        "widget_id": parsed["widget_id"],
        "widget_type": parsed["widget_type"],
        "title": parsed["title"],
        "description": parsed.get("description", ""),
        "html": parsed["html"],
        "width": parsed.get("width", "100%"),
        "height": parsed.get("height", "400px"),
    }

    # The LLM gets a compact confirmation (not the full HTML)
    llm_result = json.dumps({
        "status": "rendered",
        "widget_id": parsed["widget_id"],
        "widget_type": parsed["widget_type"],
        "title": parsed["title"],
        "message": "Widget rendered successfully in the Forge console. The user can see and interact with it.",
    })

    return widget_event, llm_result
