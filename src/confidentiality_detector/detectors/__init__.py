"""Detectors share one interface: detect(text) -> list[Span]; detect_batch(texts).

Submodules are imported lazily so that each detector only pulls in its own dependencies:
importing `detectors.transformer` or `detectors.hybrid` must not require `phonenumbers`
(rules) or `presidio_analyzer` (presidio).
"""

from importlib import import_module

_EXPORTS = {
    "HybridDetector": ".hybrid",
    "merge": ".hybrid",
    "RuleDetector": ".rules",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
