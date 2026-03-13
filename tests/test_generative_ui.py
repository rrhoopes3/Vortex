"""
Tests for the Generative UI module — interactive widget rendering.

Covers: build_widget_html, handle_render_widget, intercept_widget_result,
        register_widget_tools, WIDGET_TYPES, CDN_LIBS.
"""
import json
import pytest

from forge.generative_ui import (
    build_widget_html,
    handle_render_widget,
    intercept_widget_result,
    register_widget_tools,
    WIDGET_TYPES,
    CDN_LIBS,
    DESIGN_GUIDELINES,
    RENDER_WIDGET_SCHEMA,
)


# ── build_widget_html ─────────────────────────────────────────────────────────

class TestBuildWidgetHtml:
    def test_basic_output(self):
        html = build_widget_html(
            widget_type="chart",
            title="Test Chart",
            html_content="<canvas id='c'></canvas>",
        )
        assert "<!DOCTYPE html>" in html
        assert "Test Chart" in html
        assert "<canvas id='c'></canvas>" in html
        assert "ForgeWidget" in html

    def test_includes_cdn_libraries(self):
        html = build_widget_html(
            widget_type="chart",
            title="Chart",
            html_content="<canvas></canvas>",
            libraries=["chart.js", "d3"],
        )
        assert "chart.umd.min.js" in html
        assert "d3.min.js" in html

    def test_includes_custom_css_and_js(self):
        html = build_widget_html(
            widget_type="custom",
            title="Custom",
            html_content="<div>hi</div>",
            css=".custom-class { color: red; }",
            js="console.log('hello');",
        )
        assert ".custom-class { color: red; }" in html
        assert "console.log('hello');" in html

    def test_forge_theme_tokens(self):
        html = build_widget_html(
            widget_type="dashboard",
            title="Dash",
            html_content="<p>metrics</p>",
        )
        assert "--accent: #f2a74b" in html
        assert "--signal: #63c7b2" in html
        assert "--bg: #0b0e12" in html

    def test_katex_includes_css(self):
        html = build_widget_html(
            widget_type="custom",
            title="Math",
            html_content="<div id='math'></div>",
            libraries=["katex"],
        )
        assert "katex.min.css" in html
        assert "katex.min.js" in html

    def test_widget_bridge(self):
        html = build_widget_html(
            widget_type="form",
            title="Form",
            html_content="<form></form>",
        )
        assert "ForgeWidget" in html
        assert "forge-widget" in html
        assert "window.parent.postMessage" in html

    def test_unknown_library_ignored(self):
        html = build_widget_html(
            widget_type="custom",
            title="Test",
            html_content="<div></div>",
            libraries=["nonexistent-lib"],
        )
        assert "nonexistent-lib" not in html


# ── handle_render_widget ──────────────────────────────────────────────────────

class TestHandleRenderWidget:
    def test_valid_widget(self):
        result = handle_render_widget(
            widget_type="chart",
            title="Sales Chart",
            html="<canvas id='chart'></canvas>",
            js="new Chart(document.getElementById('chart'), {})",
            libraries=["chart.js"],
        )
        assert result["_widget"] is True
        assert result["widget_type"] == "chart"
        assert result["title"] == "Sales Chart"
        assert "widget_id" in result
        assert "<!DOCTYPE html>" in result["html"]

    def test_invalid_widget_type(self):
        result = handle_render_widget(
            widget_type="hologram",
            title="Fail",
            html="<p>nope</p>",
        )
        assert "error" in result
        assert "hologram" in result["error"]

    def test_all_widget_types_valid(self):
        for wtype in WIDGET_TYPES:
            result = handle_render_widget(
                widget_type=wtype,
                title=f"Test {wtype}",
                html=f"<div>{wtype}</div>",
            )
            assert result["_widget"] is True
            assert result["widget_type"] == wtype

    def test_default_dimensions(self):
        result = handle_render_widget(
            widget_type="custom",
            title="Default Size",
            html="<p>content</p>",
        )
        assert result["width"] == "100%"
        assert result["height"] == "400px"

    def test_custom_dimensions(self):
        result = handle_render_widget(
            widget_type="3d",
            title="3D Scene",
            html="<div id='scene'></div>",
            width="800px",
            height="600px",
        )
        assert result["width"] == "800px"
        assert result["height"] == "600px"

    def test_description_passthrough(self):
        result = handle_render_widget(
            widget_type="dashboard",
            title="Metrics",
            html="<div></div>",
            description="Real-time performance metrics",
        )
        assert result["description"] == "Real-time performance metrics"


# ── intercept_widget_result ───────────────────────────────────────────────────

class TestInterceptWidgetResult:
    def test_non_widget_passthrough(self):
        result = '{"files": ["a.txt", "b.txt"]}'
        event, llm_result = intercept_widget_result(result)
        assert event is None
        assert llm_result == result

    def test_non_json_passthrough(self):
        result = "plain text result"
        event, llm_result = intercept_widget_result(result)
        assert event is None
        assert llm_result == result

    def test_widget_intercepted(self):
        widget_payload = {
            "_widget": True,
            "widget_id": "abc12345",
            "widget_type": "chart",
            "title": "Revenue",
            "description": "Monthly revenue",
            "html": "<html>...</html>",
            "width": "100%",
            "height": "400px",
        }
        result = json.dumps(widget_payload)
        event, llm_result = intercept_widget_result(result)

        assert event is not None
        assert event["type"] == "widget_render"
        assert event["widget_id"] == "abc12345"
        assert event["widget_type"] == "chart"
        assert event["title"] == "Revenue"
        assert event["html"] == "<html>...</html>"

        # LLM gets a compact confirmation
        llm_parsed = json.loads(llm_result)
        assert llm_parsed["status"] == "rendered"
        assert llm_parsed["widget_id"] == "abc12345"
        assert "html" not in llm_parsed  # HTML not sent back to LLM

    def test_widget_false_not_intercepted(self):
        result = json.dumps({"_widget": False, "data": "test"})
        event, llm_result = intercept_widget_result(result)
        assert event is None

    def test_empty_string(self):
        event, llm_result = intercept_widget_result("")
        assert event is None
        assert llm_result == ""


# ── register_widget_tools ─────────────────────────────────────────────────────

class TestRegisterWidgetTools:
    def test_registers_render_widget(self):
        from forge.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_widget_tools(reg)
        assert "render_widget" in reg.list_tools()

    def test_tool_execution_returns_widget(self):
        from forge.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_widget_tools(reg)
        result = reg.execute("render_widget", {
            "widget_type": "chart",
            "title": "Test",
            "html": "<canvas></canvas>",
        })
        parsed = json.loads(result)
        assert parsed["_widget"] is True

    def test_tool_execution_invalid_type(self):
        from forge.tools.registry import ToolRegistry
        reg = ToolRegistry()
        register_widget_tools(reg)
        result = reg.execute("render_widget", {
            "widget_type": "hologram",
            "title": "Fail",
            "html": "<p>x</p>",
        })
        parsed = json.loads(result)
        assert "error" in parsed


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_widget_types_non_empty(self):
        assert len(WIDGET_TYPES) >= 8

    def test_cdn_libs_valid_urls(self):
        for name, url in CDN_LIBS.items():
            assert url.startswith("https://"), f"CDN lib {name} has invalid URL: {url}"

    def test_design_guidelines_content(self):
        assert "Color Palette" in DESIGN_GUIDELINES
        assert "#f2a74b" in DESIGN_GUIDELINES
        assert "Chart.js" in DESIGN_GUIDELINES

    def test_schema_required_fields(self):
        assert "widget_type" in RENDER_WIDGET_SCHEMA["required"]
        assert "title" in RENDER_WIDGET_SCHEMA["required"]
        assert "html" in RENDER_WIDGET_SCHEMA["required"]

    def test_schema_has_all_properties(self):
        props = RENDER_WIDGET_SCHEMA["properties"]
        expected = {"widget_type", "title", "html", "css", "js", "libraries", "width", "height", "description"}
        assert expected == set(props.keys())
