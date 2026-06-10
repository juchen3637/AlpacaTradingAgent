"""Speculation engine — scans broad market news and identifies speculative plays."""

from .engine import SpeculationEngine
from .models import SpeculationEvent, SpeculativePlay

__all__ = ["SpeculationEngine", "SpeculationEvent", "SpeculativePlay"]
