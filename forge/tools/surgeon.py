"""Forge tool bindings for The Surgeon — model surgery via OBLITERATUS.

Exposes abliteration (refusal direction removal) as standard Forge tools.
All heavy ML imports are lazy — tools gracefully report missing dependencies
rather than crashing the entire tool registry.

Tools:
    surgeon_check    — Verify ML dependencies, GPU, OBLITERATUS source
    surgeon_methods  — List available abliteration methods with descriptions
    surgeon_scan     — Probe a model's refusal geometry (no modification)
    surgeon_operate  — Run full abliteration pipeline (SUMMON→REBIRTH)
    surgeon_analyze  — Run specific analysis modules on a model
    surgeon_compare  — A/B test prompts on original vs modified model
    surgeon_status   — Get detailed results of a completed operation
    surgeon_list     — List all saved operations
"""
from __future__ import annotations

import json
from .registry import ToolRegistry


# ── Tool Implementations ─────────────────────────────────────────────────────

def surgeon_check() -> str:
    """Check ML dependencies, GPU availability, and OBLITERATUS source."""
    try:
        from forge.surgeon.engine import check_dependencies
        result = check_dependencies()
        result["status"] = "ready" if result["ready"] else "missing_dependencies"
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_methods() -> str:
    """List all available abliteration methods with their configurations."""
    try:
        from forge.surgeon.engine import AVAILABLE_METHODS, ANALYSIS_MODULES
        return json.dumps({
            "status": "ok",
            "methods": AVAILABLE_METHODS,
            "analysis_modules": ANALYSIS_MODULES,
            "method_count": len(AVAILABLE_METHODS),
            "analysis_module_count": len(ANALYSIS_MODULES),
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_scan(
    model_name: str,
    device: str = "auto",
    dtype: str = "float16",
    quantization: str = "",
) -> str:
    """Scan a model's refusal geometry without modifying it."""
    try:
        from forge.surgeon.engine import check_dependencies, scan_model

        deps = check_dependencies()
        if not deps["ready"]:
            return json.dumps({
                "error": "ML dependencies not installed",
                "missing": deps["missing"],
                "install_command": deps["install_command"],
            })

        logs = []
        result = scan_model(
            model_name=model_name,
            device=device,
            dtype=dtype,
            quantization=quantization or None,
            progress_cb=lambda msg: logs.append(msg),
        )

        return json.dumps({
            "status": "ok",
            "model_name": result.model_name,
            "architecture": result.architecture,
            "num_layers": result.num_layers,
            "strong_layers": result.strong_layers,
            "strong_layer_count": len(result.strong_layers),
            "refusal_strength_per_layer": result.refusal_strength_per_layer,
            "recommended_method": result.recommended_method,
            "recommended_config": result.recommended_config,
            "log": logs[-10:],
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_operate(
    model_name: str,
    method: str = "advanced",
    device: str = "auto",
    dtype: str = "float16",
    quantization: str = "",
    output_dir: str = "",
    config_overrides: str = "",
) -> str:
    """Run the full abliteration pipeline on a HuggingFace model."""
    try:
        from forge.surgeon.engine import check_dependencies, operate

        deps = check_dependencies()
        if not deps["ready"]:
            return json.dumps({
                "error": "ML dependencies not installed",
                "missing": deps["missing"],
                "install_command": deps["install_command"],
            })

        overrides = {}
        if config_overrides:
            try:
                overrides = json.loads(config_overrides)
            except json.JSONDecodeError:
                pass

        logs = []
        record = operate(
            model_name=model_name,
            method=method,
            device=device,
            dtype=dtype,
            quantization=quantization or None,
            output_dir=output_dir or None,
            config_overrides=overrides or None,
            progress_cb=lambda msg: logs.append(msg),
        )

        result = {
            "status": "ok",
            "operation_id": record.id,
            "model_name": record.model_name,
            "method": record.method,
            "operation_status": record.status.value,
            "output_path": record.output_path,
            "stages": [
                {"name": s.name, "status": s.status, "duration": s.duration_seconds}
                for s in record.stages
            ],
            "log": logs[-20:],
        }

        if record.model_info:
            result["model_info"] = {
                "architecture": record.model_info.architecture,
                "params": record.model_info.total_params_human,
                "layers": record.model_info.num_layers,
                "hidden_size": record.model_info.hidden_size,
            }

        if record.quality_metrics:
            qm = record.quality_metrics
            result["quality_metrics"] = {
                "refusal_rate": f"{qm.refusal_rate:.1%}",
                "perplexity": round(qm.perplexity, 2),
                "coherence": round(qm.coherence, 3),
                "kl_divergence": round(qm.kl_divergence, 4),
            }

        result["next_steps"] = [
            f"Compare with original: surgeon_compare(original_model=\"{model_name}\", modified_path=\"{record.output_path}\", prompts=...)",
            f"View details: surgeon_status(operation_id=\"{record.id}\")",
        ]

        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_analyze(
    model_name: str,
    modules: str,
    device: str = "auto",
    dtype: str = "float16",
) -> str:
    """Run specific analysis modules on a model's refusal geometry.

    modules: Comma-separated list of module names (e.g., "activation_probing,logit_lens,defense_robustness")
    """
    try:
        from forge.surgeon.engine import check_dependencies, run_analysis, ANALYSIS_MODULES

        deps = check_dependencies()
        if not deps["ready"]:
            return json.dumps({
                "error": "ML dependencies not installed",
                "missing": deps["missing"],
                "install_command": deps["install_command"],
            })

        module_list = [m.strip() for m in modules.split(",") if m.strip()]
        if not module_list:
            return json.dumps({
                "error": "No modules specified",
                "available": list(ANALYSIS_MODULES.keys()),
            })

        logs = []
        results = run_analysis(
            model_name=model_name,
            modules=module_list,
            device=device,
            dtype=dtype,
            progress_cb=lambda msg: logs.append(msg),
        )

        return json.dumps({
            "status": "ok",
            "model_name": model_name,
            "modules_run": len(results),
            "results": [
                {
                    "module": r.module_name,
                    "summary": r.summary,
                    "data": r.data,
                }
                for r in results
            ],
            "log": logs[-15:],
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_compare(
    original_model: str,
    modified_path: str,
    prompts: str,
    device: str = "auto",
    max_tokens: int = 150,
) -> str:
    """A/B test: generate responses from original and modified model side-by-side.

    prompts: JSON array of prompt strings, or a single prompt string.
    """
    try:
        from forge.surgeon.engine import check_dependencies, compare_models

        deps = check_dependencies()
        if not deps["ready"]:
            return json.dumps({
                "error": "ML dependencies not installed",
                "missing": deps["missing"],
                "install_command": deps["install_command"],
            })

        # Parse prompts
        try:
            prompt_list = json.loads(prompts)
            if isinstance(prompt_list, str):
                prompt_list = [prompt_list]
        except json.JSONDecodeError:
            prompt_list = [prompts]

        logs = []
        results = compare_models(
            original_model=original_model,
            modified_path=modified_path,
            prompts=prompt_list,
            device=device,
            max_tokens=max_tokens,
            progress_cb=lambda msg: logs.append(msg),
        )

        return json.dumps({
            "status": "ok",
            "original_model": original_model,
            "modified_path": modified_path,
            "comparisons": results,
            "prompts_tested": len(results),
            "log": logs[-10:],
        })

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_status(operation_id: str) -> str:
    """Get detailed results of a surgery operation."""
    try:
        from forge.surgeon.engine import load_operation

        record = load_operation(operation_id)
        if not record:
            return json.dumps({"error": f"Operation not found: {operation_id}"})

        result = {
            "status": record.status.value,
            "operation_id": record.id,
            "model_name": record.model_name,
            "method": record.method,
            "device": record.device,
            "dtype": record.dtype,
            "created_at": record.created_at,
            "output_path": record.output_path,
            "stages": [
                {
                    "name": s.name,
                    "status": s.status,
                    "message": s.message,
                    "duration": s.duration_seconds,
                    "details": s.details,
                }
                for s in record.stages
            ],
            "config_overrides": record.config_overrides,
        }

        if record.model_info:
            mi = record.model_info
            result["model_info"] = {
                "architecture": mi.architecture,
                "params": mi.total_params_human,
                "layers": mi.num_layers,
                "heads": mi.num_heads,
                "hidden_size": mi.hidden_size,
            }

        if record.quality_metrics:
            qm = record.quality_metrics
            result["quality_metrics"] = {
                "refusal_rate": qm.refusal_rate,
                "perplexity": qm.perplexity,
                "coherence": qm.coherence,
                "kl_divergence": qm.kl_divergence,
                "effective_rank": qm.effective_rank,
            }

        if record.analyses:
            result["analyses"] = [
                {"module": a.module_name, "summary": a.summary}
                for a in record.analyses
            ]

        if record.error:
            result["error"] = record.error

        # Last N log lines
        if record.log:
            result["recent_log"] = record.log[-20:]

        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def surgeon_list() -> str:
    """List all saved surgery operations."""
    try:
        from forge.surgeon.engine import list_operations
        ops = list_operations()
        return json.dumps({"status": "ok", "operations": ops, "count": len(ops)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ── Registration ─────────────────────────────────────────────────────────────

def register(registry: ToolRegistry):
    """Register all surgeon tools with the Forge's tool registry."""

    registry.register(
        name="surgeon_check",
        description=(
            "Check if ML dependencies (PyTorch, Transformers, etc.) and OBLITERATUS "
            "source are installed. Reports GPU availability, VRAM, and missing packages. "
            "Run this first before any model surgery operations."
        ),
        parameters={"type": "object", "properties": {}},
        handler=surgeon_check,
    )

    registry.register(
        name="surgeon_methods",
        description=(
            "List all available abliteration methods (basic, advanced, aggressive, "
            "surgical, informed, nuclear, etc.) with their configurations, difficulty "
            "levels, and VRAM requirements. Also lists the 20+ analysis modules."
        ),
        parameters={"type": "object", "properties": {}},
        handler=surgeon_methods,
    )

    registry.register(
        name="surgeon_scan",
        description=(
            "Scan a HuggingFace model's refusal geometry WITHOUT modifying it. "
            "Loads the model, probes activations on harmful/harmless prompt pairs, "
            "identifies which layers carry the strongest refusal signals, and recommends "
            "an abliteration method. Non-destructive — the model is not changed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": 'HuggingFace model ID (e.g., "meta-llama/Llama-3.1-8B-Instruct")',
                },
                "device": {
                    "type": "string",
                    "description": '"auto", "cuda", "cpu", or "mps" (default: auto)',
                    "default": "auto",
                },
                "dtype": {
                    "type": "string",
                    "description": '"float16", "bfloat16", or "float32" (default: float16)',
                    "default": "float16",
                },
                "quantization": {
                    "type": "string",
                    "description": '"4bit", "8bit", or empty for no quantization',
                },
            },
            "required": ["model_name"],
        },
        handler=surgeon_scan,
    )

    registry.register(
        name="surgeon_operate",
        description=(
            "Run the FULL abliteration pipeline on a HuggingFace model. Six stages: "
            "SUMMON (load model) -> PROBE (collect activations) -> DISTILL (extract "
            "refusal directions via SVD) -> EXCISE (project out directions from weights) "
            "-> VERIFY (measure quality: perplexity, refusal rate, coherence, KL) -> "
            "REBIRTH (save modified model). Returns the output path and quality metrics."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": 'HuggingFace model ID (e.g., "gpt2", "meta-llama/Llama-3.1-8B-Instruct")',
                },
                "method": {
                    "type": "string",
                    "description": "Abliteration method: basic, advanced, aggressive, surgical, informed, nuclear, etc.",
                    "default": "advanced",
                },
                "device": {
                    "type": "string",
                    "description": '"auto", "cuda", "cpu", or "mps"',
                    "default": "auto",
                },
                "dtype": {
                    "type": "string",
                    "description": '"float16", "bfloat16", or "float32"',
                    "default": "float16",
                },
                "quantization": {
                    "type": "string",
                    "description": '"4bit", "8bit", or empty for none',
                },
                "output_dir": {
                    "type": "string",
                    "description": "Where to save the modified model (default: auto in forge data dir)",
                },
                "config_overrides": {
                    "type": "string",
                    "description": 'JSON object of parameter overrides, e.g. \'{"n_directions": 6, "regularization": 0.5}\'',
                },
            },
            "required": ["model_name"],
        },
        handler=surgeon_operate,
    )

    registry.register(
        name="surgeon_analyze",
        description=(
            "Run specific analysis modules on a model's refusal geometry. Modules include: "
            "activation_probing, logit_lens, defense_robustness, alignment_imprint, "
            "concept_geometry, causal_tracing, steering_vectors, and 15+ more. "
            "Produces detailed reports on how refusal is structured inside the model."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "HuggingFace model ID to analyze.",
                },
                "modules": {
                    "type": "string",
                    "description": "Comma-separated list of analysis modules to run.",
                },
                "device": {
                    "type": "string",
                    "description": '"auto", "cuda", "cpu", or "mps"',
                    "default": "auto",
                },
                "dtype": {
                    "type": "string",
                    "description": '"float16", "bfloat16", or "float32"',
                    "default": "float16",
                },
            },
            "required": ["model_name", "modules"],
        },
        handler=surgeon_analyze,
    )

    registry.register(
        name="surgeon_compare",
        description=(
            "A/B comparison: generate responses from both the original and modified "
            "model for the same prompts. Shows side-by-side how the surgery affected "
            "the model's behavior."
        ),
        parameters={
            "type": "object",
            "properties": {
                "original_model": {
                    "type": "string",
                    "description": "HuggingFace model ID of the original model.",
                },
                "modified_path": {
                    "type": "string",
                    "description": "Path to the modified (abliterated) model.",
                },
                "prompts": {
                    "type": "string",
                    "description": 'JSON array of prompts, or a single prompt string.',
                },
                "device": {
                    "type": "string",
                    "description": '"auto", "cuda", "cpu", or "mps"',
                    "default": "auto",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens to generate per response (default 150).",
                    "default": 150,
                },
            },
            "required": ["original_model", "modified_path", "prompts"],
        },
        handler=surgeon_compare,
    )

    registry.register(
        name="surgeon_status",
        description=(
            "Get detailed results of a completed surgery operation: pipeline stages, "
            "model architecture info, quality metrics (refusal rate, perplexity, "
            "coherence, KL divergence), and execution log."
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation_id": {
                    "type": "string",
                    "description": "The operation ID from surgeon_operate.",
                },
            },
            "required": ["operation_id"],
        },
        handler=surgeon_status,
    )

    registry.register(
        name="surgeon_list",
        description="List all saved model surgery operations with status, method, model, and metrics.",
        parameters={"type": "object", "properties": {}},
        handler=surgeon_list,
    )
