"""The Surgeon — Model surgery toolkit for The Forge.

Wraps OBLITERATUS's abliteration pipeline as Forge-native tools, enabling
the executor to probe, analyze, and surgically modify LLM weights to remove
refusal behaviors while preserving capabilities.

Usage (programmatic):
    from forge.surgeon import operate, scan_model, check_dependencies

    # Check if ML stack is installed
    deps = check_dependencies()
    if not deps["ready"]:
        print(f"Install: {deps['install_command']}")

    # Scan a model's refusal geometry
    scan = scan_model("meta-llama/Llama-3.1-8B-Instruct")
    print(scan.strong_layers)

    # Run full abliteration
    record = operate("meta-llama/Llama-3.1-8B-Instruct", method="advanced")
    print(record.output_path)
    print(record.quality_metrics)

Usage (as Forge tool):
    The surgeon tools are registered in the Forge's tool registry:
    - surgeon_check: Verify ML dependencies and GPU availability
    - surgeon_methods: List available abliteration methods
    - surgeon_scan: Probe a model's refusal geometry (no modification)
    - surgeon_operate: Run full abliteration pipeline
    - surgeon_analyze: Run specific analysis modules
    - surgeon_compare: A/B test original vs modified model
    - surgeon_status: Check operation results
    - surgeon_list: List completed operations
"""

from forge.surgeon.engine import (
    operate,
    scan_model,
    run_analysis,
    compare_models,
    check_dependencies,
    list_operations,
    load_operation,
    AVAILABLE_METHODS,
    ANALYSIS_MODULES,
)
from forge.surgeon.types import (
    OperationRecord,
    OperationStatus,
    ModelInfo,
    QualityMetrics,
    ScanResult,
    AnalysisResult,
)

__all__ = [
    # Operations
    "operate",
    "scan_model",
    "run_analysis",
    "compare_models",
    "check_dependencies",
    # Management
    "list_operations",
    "load_operation",
    # Data
    "AVAILABLE_METHODS",
    "ANALYSIS_MODULES",
    # Types
    "OperationRecord",
    "OperationStatus",
    "ModelInfo",
    "QualityMetrics",
    "ScanResult",
    "AnalysisResult",
]
