"""
Golden Evals — canonical eval flows per capability pack.

Each pack gets one or more golden eval cases that serve as:
  - Regression tests for the pack's core execution path
  - Provider comparison benchmarks (quality, latency, cost)
  - CI gates before merging changes that touch a pack's tools
"""
from forge.evals.golden import ALL_GOLDEN_EVALS, get_golden_evals

__all__ = ["ALL_GOLDEN_EVALS", "get_golden_evals"]
