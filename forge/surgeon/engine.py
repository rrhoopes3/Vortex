"""Surgeon Engine — OBLITERATUS wrapper for The Forge.

Bridges OBLITERATUS's AbliterationPipeline into the Forge's tool ecosystem.
OBLITERATUS lives in Projects/OBLITERATUS-main/ and is loaded at runtime via
sys.path injection. All heavy ML imports (torch, transformers) are lazy —
the module stays importable even without a GPU stack.

Pipeline stages map to OBLITERATUS:
    SUMMON  → load_model()
    PROBE   → collect harmful/harmless activations
    DISTILL → extract refusal directions via SVD
    EXCISE  → project out refusal directions from weights
    VERIFY  → perplexity, coherence, refusal rate, KL divergence
    REBIRTH → save modified model to disk
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

from forge.config import DATA_DIR
from forge.surgeon.types import (
    AnalysisResult, ModelInfo, OperationRecord, OperationStatus,
    QualityMetrics, ScanResult, StageInfo,
)

log = logging.getLogger("forge.surgeon")

SURGEON_DIR = DATA_DIR / "surgeon"
SURGEON_DIR.mkdir(parents=True, exist_ok=True)

# Path to OBLITERATUS source
OBLITERATUS_ROOT = Path(__file__).resolve().parent.parent.parent / "Projects" / "OBLITERATUS-main"

# Available methods (mirrors OBLITERATUS's METHODS dict without importing it)
AVAILABLE_METHODS = {
    "basic": {
        "label": "Basic (Arditi et al.)",
        "description": "Single refusal direction via difference-in-means. Fast baseline.",
        "directions": 1, "norm_preserve": False, "passes": 1,
        "difficulty": "easy", "gpu_vram_gb": 1,
    },
    "advanced": {
        "label": "Advanced (Multi-direction + Norm-preserving)",
        "description": "SVD-based multi-direction extraction with norm preservation. The default.",
        "directions": 4, "norm_preserve": True, "passes": 2,
        "difficulty": "medium", "gpu_vram_gb": 4,
    },
    "aggressive": {
        "label": "Aggressive (Full Gabliteration + Enhanced)",
        "description": "Maximum direction extraction with whitened SVD, iterative refinement, head surgery.",
        "directions": 8, "norm_preserve": True, "passes": 3,
        "difficulty": "hard", "gpu_vram_gb": 8,
    },
    "surgical": {
        "label": "Surgical (Head Surgery + SAE + Neuron Masking)",
        "description": "Precision targeting: attention head surgery, sparse autoencoder, layer-adaptive.",
        "directions": 8, "norm_preserve": True, "passes": 2,
        "difficulty": "hard", "gpu_vram_gb": 8,
    },
    "informed": {
        "label": "Informed (Analysis-Guided Auto-Configuration)",
        "description": "Runs analysis modules first, then auto-tunes every parameter. Maximum precision.",
        "directions": "auto", "norm_preserve": True, "passes": "auto",
        "difficulty": "expert", "gpu_vram_gb": 12,
    },
    "nuclear": {
        "label": "Nuclear (All SOTA Techniques)",
        "description": "Every technique enabled: expert transplant, steering vectors, CoT-aware, KL-optimized.",
        "directions": 4, "norm_preserve": True, "passes": 3,
        "difficulty": "extreme", "gpu_vram_gb": 16,
    },
    "spectral_cascade": {
        "label": "Spectral Cascade (Frequency-Domain)",
        "description": "DCT frequency-domain decomposition of refusal signals. Novel approach.",
        "directions": 6, "norm_preserve": True, "passes": 1,
        "difficulty": "medium", "gpu_vram_gb": 6,
    },
    "inverted": {
        "label": "Inverted (Semantic Reflection)",
        "description": "Instead of removing refusal, reflects it — experimental inversion.",
        "directions": 8, "norm_preserve": True, "passes": 2,
        "difficulty": "hard", "gpu_vram_gb": 8,
    },
    "optimized": {
        "label": "Optimized (Bayesian-Tuned)",
        "description": "Optuna TPE search over hyperparameters. 50 trials to find optimal config.",
        "directions": 4, "norm_preserve": True, "passes": "auto",
        "difficulty": "expert", "gpu_vram_gb": 12,
    },
    "failspy": {
        "label": "FailSpy (Middle-60% Layers)",
        "description": "FailSpy-style baseline: target middle 60% of layers only.",
        "directions": 1, "norm_preserve": False, "passes": 1,
        "difficulty": "easy", "gpu_vram_gb": 2,
    },
    "gabliteration": {
        "label": "Gabliteration (Original Method)",
        "description": "Original Gabliteration (arXiv:2512.18901) implementation.",
        "directions": 4, "norm_preserve": True, "passes": 1,
        "difficulty": "medium", "gpu_vram_gb": 4,
    },
}

# Available analysis modules
ANALYSIS_MODULES = {
    "activation_patching": "Map causal impact of each layer on refusal decisions",
    "activation_probing": "Per-layer refusal signal strength measurement",
    "alignment_imprint": "Fingerprint alignment method (DPO vs RLHF vs CAI vs SFT)",
    "anti_ouroboros": "Detect self-repair mechanisms that re-emerge after ablation",
    "bayesian_kernel_projection": "Bayesian kernel analysis of refusal geometry",
    "causal_tracing": "Trace causal necessity of components for refusal",
    "concept_geometry": "Map polyhedral geometry of refusal cones",
    "conditional_abliteration": "Category-specific refusal targeting",
    "cross_layer": "Direction evolution and alignment across layers",
    "cross_model_transfer": "Measure direction universality across models",
    "defense_robustness": "Ouroboros effect and safety-capability entanglement",
    "leace": "Optimal concept erasure via generalized eigenvalue problem",
    "logit_lens": "Decode refusal direction through the logit lens",
    "multi_token_position": "Sequence position analysis of refusal signal",
    "probing_classifiers": "Train linear classifiers on refusal features",
    "residual_stream": "Attention vs MLP refusal attribution decomposition",
    "riemannian_manifold": "Manifold structure: geodesics and curvature",
    "sae_abliteration": "Sparse autoencoder feature decomposition",
    "sparse_surgery": "High-precision weight row analysis for sparse directions",
    "spectral_certification": "Spectral analysis and certification bounds",
    "steering_vectors": "Inference-time steering vector extraction",
    "tuned_lens": "Tuned lens probing across layers",
}


# ── Dependency Checking ──────────────────────────────────────────────────────

def check_dependencies() -> dict[str, Any]:
    """Check whether all required ML dependencies are available."""
    deps = {}
    missing = []

    for pkg in ["torch", "transformers", "accelerate", "safetensors", "datasets"]:
        try:
            mod = __import__(pkg)
            deps[pkg] = getattr(mod, "__version__", "installed")
        except ImportError:
            deps[pkg] = None
            missing.append(pkg)

    # Check OBLITERATUS source
    deps["obliteratus_source"] = str(OBLITERATUS_ROOT) if OBLITERATUS_ROOT.exists() else None

    # Check GPU
    try:
        import torch
        deps["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            deps["gpu_name"] = torch.cuda.get_device_name(0)
            deps["gpu_vram_gb"] = round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1)
        deps["mps_available"] = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    except ImportError:
        deps["cuda_available"] = False
        deps["mps_available"] = False

    return {
        "installed": deps,
        "missing": missing,
        "ready": len(missing) == 0 and deps.get("obliteratus_source") is not None,
        "install_command": f"pip install torch transformers accelerate safetensors datasets"
        if missing else None,
    }


def _ensure_obliteratus():
    """Add OBLITERATUS to sys.path and verify it's importable."""
    if not OBLITERATUS_ROOT.exists():
        raise RuntimeError(
            f"OBLITERATUS source not found at {OBLITERATUS_ROOT}. "
            f"Place the OBLITERATUS-main folder in B:/Grok/Projects/"
        )
    src = str(OBLITERATUS_ROOT)
    if src not in sys.path:
        sys.path.insert(0, src)

    # Verify import works
    try:
        import obliteratus  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            f"OBLITERATUS found but can't import: {e}. "
            f"Install dependencies: pip install torch transformers accelerate safetensors datasets"
        ) from e


# ── Core Operations ──────────────────────────────────────────────────────────

def operate(
    model_name: str,
    method: str = "advanced",
    device: str = "auto",
    dtype: str = "float16",
    quantization: str | None = None,
    output_dir: str | None = None,
    config_overrides: dict[str, Any] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> OperationRecord:
    """Run the full abliteration pipeline on a model.

    Args:
        model_name: HuggingFace model ID (e.g., "meta-llama/Llama-3.1-8B-Instruct").
        method: Abliteration method preset.
        device: "auto", "cuda", "cpu", "mps".
        dtype: "float16", "bfloat16", "float32".
        quantization: "4bit", "8bit", or None.
        output_dir: Where to save. Defaults to surgeon data dir.
        config_overrides: Override specific pipeline parameters.
        progress_cb: Called with status messages.

    Returns:
        OperationRecord with full results.
    """
    _ensure_obliteratus()

    def emit(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # Create record
    record = OperationRecord(
        model_name=model_name,
        method=method,
        device=device,
        dtype=dtype,
        quantization=quantization or "",
        config_overrides=config_overrides or {},
    )

    if not output_dir:
        output_dir = str(SURGEON_DIR / "models" / record.id)

    emit(f"[SURGEON] Preparing operation: {model_name} (method={method})")

    try:
        from obliteratus.abliterate import AbliterationPipeline, METHODS

        # Build pipeline kwargs
        kwargs: dict[str, Any] = {
            "model_name": model_name,
            "output_dir": output_dir,
            "device": device,
            "dtype": dtype,
            "method": method,
        }
        if quantization:
            kwargs["quantization"] = quantization

        # Apply config overrides
        if config_overrides:
            kwargs.update(config_overrides)

        # Stage tracking
        stage_map: dict[str, StageInfo] = {}

        def on_stage(stage_result):
            """Callback from OBLITERATUS pipeline — maps to our StageInfo."""
            name = stage_result.stage
            status = stage_result.status

            if name not in stage_map:
                info = StageInfo(name=name)
                stage_map[name] = info
                record.stages.append(info)

            info = stage_map[name]
            info.status = status
            info.message = stage_result.message or ""
            if hasattr(stage_result, "duration") and stage_result.duration:
                info.duration_seconds = stage_result.duration

            # Extract useful details
            for key in ("architecture", "num_layers", "num_heads", "hidden_size",
                        "total_params", "intermediate_size"):
                if hasattr(stage_result, key):
                    info.details[key] = getattr(stage_result, key)

            # Update record status based on current stage
            status_map = {
                "summon": OperationStatus.LOADING,
                "probe": OperationStatus.PROBING,
                "distill": OperationStatus.DISTILLING,
                "excise": OperationStatus.EXCISING,
                "verify": OperationStatus.VERIFYING,
                "rebirth": OperationStatus.SAVING,
            }
            if name in status_map:
                record.status = status_map[name]
                emit(f"[SURGEON] Stage {name.upper()}: {info.message}")

        def on_log(msg: str):
            record.log.append(msg)
            if len(record.log) > 200:
                record.log = record.log[-150:]

        kwargs["on_stage"] = on_stage
        kwargs["on_log"] = on_log

        # Run pipeline
        emit(f"[SURGEON] Starting {method} abliteration on {model_name}")
        pipeline = AbliterationPipeline(**kwargs)
        output_path = pipeline.run()

        # Extract results
        record.output_path = str(output_path)
        record.status = OperationStatus.COMPLETED

        # Model info
        if pipeline.handle:
            summary = pipeline.handle.summary()
            total = summary.get("total_params", 0)
            record.model_info = ModelInfo(
                model_name=model_name,
                architecture=summary.get("architecture", ""),
                num_layers=summary.get("num_layers", 0),
                num_heads=summary.get("num_heads", 0),
                hidden_size=summary.get("hidden_size", 0),
                intermediate_size=summary.get("intermediate_size", 0),
                total_params=total,
                total_params_human=_human_params(total),
            )

        # Quality metrics
        metrics = getattr(pipeline, "_quality_metrics", {})
        if metrics:
            record.quality_metrics = QualityMetrics(
                refusal_rate=metrics.get("refusal_rate", 0),
                perplexity=metrics.get("perplexity", 0),
                coherence=metrics.get("coherence", 0),
                kl_divergence=metrics.get("kl_divergence", 0),
                effective_rank=metrics.get("effective_rank", 0),
            )

        emit(f"[SURGEON] Operation complete. Model saved to: {output_path}")
        if record.quality_metrics:
            qm = record.quality_metrics
            emit(f"[SURGEON] Refusal rate: {qm.refusal_rate:.1%} | "
                 f"Perplexity: {qm.perplexity:.2f} | "
                 f"Coherence: {qm.coherence:.2f} | "
                 f"KL: {qm.kl_divergence:.4f}")

        record.save(SURGEON_DIR)
        return record

    except Exception as e:
        record.status = OperationStatus.FAILED
        record.error = f"{type(e).__name__}: {e}"
        log.exception("Surgery operation failed")
        record.save(SURGEON_DIR)
        raise


def scan_model(
    model_name: str,
    device: str = "auto",
    dtype: str = "float16",
    quantization: str | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> ScanResult:
    """Scan a model's refusal geometry without modifying it.

    Loads the model, probes activations on harmful/harmless prompts, and
    identifies which layers carry the strongest refusal signals. Recommends
    an abliteration method and configuration.
    """
    _ensure_obliteratus()

    def emit(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    emit(f"[SURGEON] Scanning refusal geometry: {model_name}")

    from obliteratus.abliterate import AbliterationPipeline

    # Create pipeline but only run SUMMON + PROBE + DISTILL (no EXCISE)
    logs: list[str] = []
    pipeline = AbliterationPipeline(
        model_name=model_name,
        output_dir=str(SURGEON_DIR / "scans" / "temp"),
        device=device,
        dtype=dtype,
        method="basic",  # cheapest for scanning
        quantization=quantization,
        on_log=lambda m: logs.append(m),
    )

    # Run only the analysis stages
    pipeline._summon()
    emit("[SURGEON] Model loaded, probing activations...")
    pipeline._probe()
    emit("[SURGEON] Distilling refusal directions...")
    pipeline._distill()

    # Extract scan results
    summary = pipeline.handle.summary() if pipeline.handle else {}
    strong_layers = list(pipeline._strong_layers)

    # Compute per-layer refusal strength from directions
    strength_per_layer = {}
    for layer_idx, direction in pipeline.refusal_directions.items():
        import torch
        strength_per_layer[str(layer_idx)] = float(torch.norm(direction).item())

    # Recommend method based on model size and architecture
    total_params = summary.get("total_params", 0)
    if total_params > 100_000_000_000:  # 100B+
        rec_method = "advanced"
        rec_note = "Large model — advanced method with conservative defaults"
    elif total_params > 10_000_000_000:  # 10B+
        rec_method = "advanced"
        rec_note = "Medium model — advanced method recommended"
    elif total_params > 1_000_000_000:  # 1B+
        rec_method = "aggressive"
        rec_note = "Small-medium model — aggressive method for thorough removal"
    else:
        rec_method = "nuclear"
        rec_note = "Small model — nuclear method feasible"

    result = ScanResult(
        model_name=model_name,
        architecture=summary.get("architecture", ""),
        num_layers=summary.get("num_layers", 0),
        strong_layers=strong_layers,
        refusal_strength_per_layer=strength_per_layer,
        recommended_method=rec_method,
        recommended_config={
            "note": rec_note,
            "total_params": total_params,
            "total_params_human": _human_params(total_params),
            "strong_layer_count": len(strong_layers),
            "total_layers": summary.get("num_layers", 0),
        },
    )

    emit(f"[SURGEON] Scan complete: {len(strong_layers)} strong layers out of {summary.get('num_layers', '?')}")
    emit(f"[SURGEON] Recommended method: {rec_method} — {rec_note}")

    # Cleanup model from memory
    del pipeline
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        import gc
        gc.collect()
    except ImportError:
        pass

    return result


def run_analysis(
    model_name: str,
    modules: list[str],
    device: str = "auto",
    dtype: str = "float16",
    progress_cb: Callable[[str], None] | None = None,
) -> list[AnalysisResult]:
    """Run specific analysis modules on a model.

    Available modules: see ANALYSIS_MODULES dict.
    """
    _ensure_obliteratus()

    def emit(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    emit(f"[SURGEON] Running {len(modules)} analysis modules on {model_name}")

    # Validate modules
    valid = []
    for m in modules:
        if m in ANALYSIS_MODULES:
            valid.append(m)
        else:
            emit(f"[SURGEON] Unknown module: {m} — skipping")

    if not valid:
        raise ValueError(f"No valid analysis modules. Available: {list(ANALYSIS_MODULES.keys())}")

    # Load model via pipeline (SUMMON + PROBE + DISTILL)
    from obliteratus.abliterate import AbliterationPipeline

    pipeline = AbliterationPipeline(
        model_name=model_name,
        output_dir=str(SURGEON_DIR / "analysis" / "temp"),
        device=device,
        dtype=dtype,
        method="basic",
    )
    pipeline._summon()
    pipeline._probe()
    pipeline._distill()

    results = []

    for module_name in valid:
        emit(f"[SURGEON] Running analysis: {module_name}")
        try:
            result = _run_single_analysis(pipeline, module_name)
            results.append(result)
            emit(f"[SURGEON] {module_name}: {result.summary[:100]}")
        except Exception as e:
            emit(f"[SURGEON] {module_name} failed: {e}")
            results.append(AnalysisResult(
                module_name=module_name,
                summary=f"Failed: {type(e).__name__}: {e}",
            ))

    # Cleanup
    del pipeline
    try:
        import torch, gc
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
    except ImportError:
        pass

    return results


def _run_single_analysis(pipeline, module_name: str) -> AnalysisResult:
    """Run a single analysis module against a probed pipeline."""
    import torch

    handle = pipeline.handle
    directions = pipeline.refusal_directions
    subspaces = pipeline.refusal_subspaces
    strong_layers = pipeline._strong_layers
    harmful_means = pipeline._harmful_means
    harmless_means = pipeline._harmless_means

    # Import the specific analysis module
    analysis_mod = __import__(
        f"obliteratus.analysis.{module_name}", fromlist=[module_name]
    )

    # Each module has different interfaces — handle the common ones
    if module_name == "activation_probing":
        prober = analysis_mod.ActivationProbe(handle)
        scores = prober.score_layers(harmful_means, harmless_means)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Strongest refusal layers: {scores[:5]}",
            data={"layer_scores": {str(k): float(v) for k, v in enumerate(scores)
                                   if isinstance(v, (int, float))}},
        )

    elif module_name == "logit_lens":
        lens = analysis_mod.RefusalLogitLens(handle)
        result = lens.decode_directions(directions)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Refusal crystallization analysis complete",
            data={"decoded": str(result)[:2000]},
        )

    elif module_name == "defense_robustness":
        evaluator = analysis_mod.DefenseRobustnessEvaluator(handle)
        report = evaluator.evaluate(directions, strong_layers)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Defense robustness evaluated",
            data={"report": str(report)[:2000]},
        )

    elif module_name == "alignment_imprint":
        detector = analysis_mod.AlignmentImprintDetector()
        result = detector.detect(subspaces, strong_layers)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Alignment training method fingerprinted",
            data={"imprint": str(result)[:2000]},
        )

    elif module_name == "concept_geometry":
        analyzer = analysis_mod.ConceptConeAnalyzer()
        result = analyzer.analyze(directions, strong_layers)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Concept geometry mapped",
            data={"geometry": str(result)[:2000]},
        )

    elif module_name == "steering_vectors":
        factory = analysis_mod.SteeringVectorFactory(handle)
        vectors = factory.extract(directions, strong_layers)
        return AnalysisResult(
            module_name=module_name,
            summary=f"Extracted {len(vectors) if hasattr(vectors, '__len__') else '?'} steering vectors",
            data={"count": len(vectors) if hasattr(vectors, "__len__") else 0},
        )

    else:
        # Generic fallback — try to instantiate and call common methods
        return AnalysisResult(
            module_name=module_name,
            summary=f"Module {module_name} loaded (use programmatic API for full access)",
            data={"available": True, "description": ANALYSIS_MODULES.get(module_name, "")},
        )


def compare_models(
    original_model: str,
    modified_path: str,
    prompts: list[str],
    device: str = "auto",
    max_tokens: int = 150,
    progress_cb: Callable[[str], None] | None = None,
) -> list[dict]:
    """Generate responses from both original and modified models for comparison."""
    _ensure_obliteratus()

    def emit(msg: str):
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    emit(f"[SURGEON] Comparing {original_model} vs {modified_path}")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    results = []

    # Load original
    emit("[SURGEON] Loading original model...")
    orig_tokenizer = AutoTokenizer.from_pretrained(original_model, trust_remote_code=True)
    orig_model = AutoModelForCausalLM.from_pretrained(
        original_model, device_map=device, torch_dtype=torch.float16, trust_remote_code=True
    )

    # Load modified
    emit("[SURGEON] Loading modified model...")
    mod_tokenizer = AutoTokenizer.from_pretrained(modified_path, trust_remote_code=True)
    mod_model = AutoModelForCausalLM.from_pretrained(
        modified_path, device_map=device, torch_dtype=torch.float16, trust_remote_code=True
    )

    for i, prompt in enumerate(prompts):
        emit(f"[SURGEON] Testing prompt {i + 1}/{len(prompts)}: {prompt[:60]}...")

        # Original
        inputs = orig_tokenizer(prompt, return_tensors="pt").to(orig_model.device)
        with torch.no_grad():
            orig_ids = orig_model.generate(**inputs, max_new_tokens=max_tokens, do_sample=True, temperature=0.7)
        orig_text = orig_tokenizer.decode(orig_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

        # Modified
        inputs = mod_tokenizer(prompt, return_tensors="pt").to(mod_model.device)
        with torch.no_grad():
            mod_ids = mod_model.generate(**inputs, max_new_tokens=max_tokens, do_sample=True, temperature=0.7)
        mod_text = mod_tokenizer.decode(mod_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

        results.append({
            "prompt": prompt,
            "original_response": orig_text[:500],
            "modified_response": mod_text[:500],
        })

    # Cleanup
    del orig_model, mod_model
    try:
        torch.cuda.empty_cache()
        import gc
        gc.collect()
    except Exception:
        pass

    emit(f"[SURGEON] Comparison complete: {len(results)} prompts tested")
    return results


# ── Management ───────────────────────────────────────────────────────────────

def list_operations() -> list[dict]:
    """List all saved operation records."""
    ops = []
    for path in sorted(SURGEON_DIR.glob("surgeon_*.json"), reverse=True):
        try:
            record = OperationRecord.load(path)
            entry = {
                "id": record.id,
                "model_name": record.model_name,
                "method": record.method,
                "status": record.status.value,
                "created_at": record.created_at,
                "output_path": record.output_path,
            }
            if record.quality_metrics:
                entry["refusal_rate"] = record.quality_metrics.refusal_rate
                entry["perplexity"] = record.quality_metrics.perplexity
            if record.model_info:
                entry["params"] = record.model_info.total_params_human
            if record.error:
                entry["error"] = record.error[:200]
            ops.append(entry)
        except Exception as e:
            log.warning("Failed to load operation %s: %s", path.name, e)
    return ops


def load_operation(op_id: str) -> OperationRecord | None:
    """Load an operation record by ID."""
    path = SURGEON_DIR / f"{op_id}.json"
    if not path.exists():
        for p in SURGEON_DIR.glob(f"*{op_id}*.json"):
            path = p
            break
        else:
            return None
    return OperationRecord.load(path)


def _human_params(n: int) -> str:
    """Convert parameter count to human-readable string."""
    if n >= 1e12:
        return f"{n / 1e12:.1f}T"
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return str(n)
