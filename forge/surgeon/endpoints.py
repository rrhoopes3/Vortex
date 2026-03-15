"""Flask Blueprint for Surgeon (OBLITERATUS) API endpoints."""

from __future__ import annotations

import json
import logging
import threading

from flask import Blueprint, Response, jsonify, request

log = logging.getLogger("forge.surgeon.endpoints")

surgeon_bp = Blueprint("surgeon", __name__, url_prefix="/api/surgeon")

# In-flight operation tracking
_operations: dict[str, dict] = {}  # op_id → {"status", "thread", "record", "error", "logs"}


@surgeon_bp.route("/check")
def check_deps():
    """Check if ML dependencies and GPU are available."""
    from forge.surgeon import check_dependencies
    return jsonify(check_dependencies())


@surgeon_bp.route("/methods")
def list_methods():
    """List available abliteration methods with descriptions."""
    from forge.surgeon import AVAILABLE_METHODS
    return jsonify({"methods": AVAILABLE_METHODS})


@surgeon_bp.route("/analysis-modules")
def list_analysis_modules():
    """List available analysis modules."""
    from forge.surgeon import ANALYSIS_MODULES
    return jsonify({"modules": ANALYSIS_MODULES})


@surgeon_bp.route("/operations")
def list_ops():
    """List completed operations."""
    from forge.surgeon import list_operations
    ops = list_operations()
    return jsonify({"operations": [
        {
            "id": op.id,
            "model_name": op.model_name,
            "method": op.method,
            "status": op.status.value,
            "created_at": op.created_at,
            "output_path": op.output_path,
            "error": op.error,
        }
        for op in ops
    ]})


@surgeon_bp.route("/operations/<op_id>")
def get_operation(op_id: str):
    """Get full operation record."""
    from forge.surgeon import load_operation
    op = load_operation(op_id)
    if not op:
        return jsonify({"error": "Operation not found"}), 404
    return jsonify(op.model_dump())


@surgeon_bp.route("/scan", methods=["POST"])
def scan():
    """Scan a model's refusal geometry (non-destructive)."""
    data = request.get_json() or {}
    model_name = data.get("model_name", "").strip()
    if not model_name:
        return jsonify({"error": "No model_name provided"}), 400

    from forge.surgeon import check_dependencies
    deps = check_dependencies()
    if not deps["ready"]:
        return jsonify({
            "error": "ML dependencies not installed",
            "install_command": deps.get("install_command", ""),
            "missing": deps.get("missing", []),
        }), 503

    from forge.surgeon import scan_model
    try:
        result = scan_model(
            model_name,
            device=data.get("device", "auto"),
            dtype=data.get("dtype", "float16"),
        )
        return jsonify(result.model_dump())
    except Exception as e:
        log.exception("Scan failed")
        return jsonify({"error": str(e)}), 500


@surgeon_bp.route("/operate", methods=["POST"])
def operate():
    """Run full abliteration pipeline. Non-blocking — starts background thread."""
    data = request.get_json() or {}
    model_name = data.get("model_name", "").strip()
    if not model_name:
        return jsonify({"error": "No model_name provided"}), 400

    from forge.surgeon import check_dependencies
    deps = check_dependencies()
    if not deps["ready"]:
        return jsonify({
            "error": "ML dependencies not installed",
            "install_command": deps.get("install_command", ""),
            "missing": deps.get("missing", []),
        }), 503

    method = data.get("method", "advanced")
    device = data.get("device", "auto")
    dtype = data.get("dtype", "float16")
    quantization = data.get("quantization", "")

    import uuid
    op_id = f"op_{uuid.uuid4().hex[:8]}"
    tracker = {"status": "running", "record": None, "error": None, "logs": []}
    _operations[op_id] = tracker

    def _bg():
        from forge.surgeon import operate as surgeon_operate
        try:
            def on_log(msg):
                tracker["logs"].append(msg)
                if len(tracker["logs"]) > 100:
                    tracker["logs"] = tracker["logs"][-50:]

            record = surgeon_operate(
                model_name,
                method=method,
                device=device,
                dtype=dtype,
                quantization=quantization,
                on_log=on_log,
            )
            tracker["record"] = record
            tracker["status"] = "done"
        except Exception as e:
            log.exception("Operation %s failed", op_id)
            tracker["status"] = "error"
            tracker["error"] = str(e)

    t = threading.Thread(target=_bg, daemon=True)
    t.start()

    return jsonify({"op_id": op_id, "status": "started"})


@surgeon_bp.route("/operate/<op_id>/status")
def operate_status(op_id: str):
    """Check in-flight operation status."""
    if op_id not in _operations:
        return jsonify({"error": "Operation not found"}), 404

    tracker = _operations[op_id]
    result = {
        "op_id": op_id,
        "status": tracker["status"],
        "recent_logs": tracker["logs"][-10:],
    }
    if tracker.get("error"):
        result["error"] = tracker["error"]
    if tracker.get("record"):
        result["record"] = tracker["record"].model_dump()
    return jsonify(result)


@surgeon_bp.route("/analyze", methods=["POST"])
def analyze():
    """Run specific analysis modules on a model."""
    data = request.get_json() or {}
    model_name = data.get("model_name", "").strip()
    modules = data.get("modules", [])
    if not model_name:
        return jsonify({"error": "No model_name provided"}), 400

    from forge.surgeon import check_dependencies
    deps = check_dependencies()
    if not deps["ready"]:
        return jsonify({
            "error": "ML dependencies not installed",
            "install_command": deps.get("install_command", ""),
        }), 503

    from forge.surgeon import run_analysis
    try:
        results = run_analysis(model_name, modules=modules)
        return jsonify({"results": [r.model_dump() for r in results]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@surgeon_bp.route("/compare", methods=["POST"])
def compare():
    """Compare original vs modified model outputs."""
    data = request.get_json() or {}
    original = data.get("original_model", "").strip()
    modified = data.get("modified_model", "").strip()
    prompts = data.get("prompts", [])
    if not original or not modified:
        return jsonify({"error": "Both original_model and modified_model required"}), 400

    from forge.surgeon import check_dependencies
    deps = check_dependencies()
    if not deps["ready"]:
        return jsonify({
            "error": "ML dependencies not installed",
            "install_command": deps.get("install_command", ""),
        }), 503

    from forge.surgeon import compare_models
    try:
        result = compare_models(original, modified, prompts=prompts)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
