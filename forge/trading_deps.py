"""Runtime dependency checks for optional trading providers."""
from __future__ import annotations

import importlib.util

_PROVIDER_LABELS = {
    "robinhood": "Robinhood",
    "robinhood-crypto": "Robinhood Crypto API",
}

_PROVIDER_DEPENDENCIES = {
    "robinhood": ("robin_stocks",),
    "robinhood-crypto": ("cryptography",),
}


def missing_provider_dependencies(provider: str) -> list[str]:
    """Return any missing optional modules required by a provider."""
    missing = []
    for module_name in _PROVIDER_DEPENDENCIES.get(provider, ()):
        if importlib.util.find_spec(module_name) is None:
            missing.append(module_name)
    return missing


def provider_dependencies_available(provider: str) -> bool:
    """True when the provider's optional runtime modules are importable."""
    return not missing_provider_dependencies(provider)


def get_provider_dependency_status(provider: str) -> dict:
    """Return provider dependency availability and a human-friendly issue."""
    missing = missing_provider_dependencies(provider)
    available = not missing
    issue = ""
    if missing:
        label = _PROVIDER_LABELS.get(provider, provider)
        modules = ", ".join(f"'{name}'" for name in missing)
        issue = (
            f"{label} requires the optional package"
            f"{'' if len(missing) == 1 else 's'} {modules}. "
            "Install the trading extras and run The Forge from that environment's Python."
        )
    return {
        "provider": provider,
        "available": available,
        "missing_dependencies": missing,
        "issue": issue,
    }


def require_provider_dependencies(provider: str) -> None:
    """Raise a friendly runtime error when a provider's optional modules are missing."""
    status = get_provider_dependency_status(provider)
    if not status["available"]:
        raise RuntimeError(status["issue"])
