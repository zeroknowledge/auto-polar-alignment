"""Star extraction.  Select a backend with ``config.extractor.backend``."""
from __future__ import annotations

from collections.abc import Callable

from ..config import ExtractorConfig
from .base import (FLAG_BLENDED, FLAG_ELONGATED, FLAG_SATURATED, ExtractionResult, StarExtractor)
from .numpy_extractor import NumpyStarExtractor

_BACKENDS: dict[str, Callable[[ExtractorConfig], StarExtractor]] = {
    "numpy": lambda cfg: NumpyStarExtractor(cfg),
}


def register_extractor(name: str, factory: Callable[[ExtractorConfig], StarExtractor]) -> None:
    """Plug in another implementation (e.g. a compiled one) without touching the aligner."""
    _BACKENDS[name] = factory


def get_extractor(cfg: ExtractorConfig | None = None) -> StarExtractor:
    cfg = cfg or ExtractorConfig()
    if cfg.backend == "tetra3" and "tetra3" not in _BACKENDS:
        from .tetra3_adapter import Tetra3Extractor
        register_extractor("tetra3", lambda c: Tetra3Extractor(c))
    try:
        return _BACKENDS[cfg.backend](cfg)
    except KeyError:
        raise ValueError(f"unknown extractor backend {cfg.backend!r}; known: {sorted(_BACKENDS)}") from None


__all__ = ["ExtractionResult", "StarExtractor", "NumpyStarExtractor", "get_extractor", "register_extractor",
           "FLAG_BLENDED", "FLAG_ELONGATED", "FLAG_SATURATED"]
