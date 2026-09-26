"""gamegraph: finite cyclic game WIN/LOSE/DRAW analyzer."""

from .analyzer import (
    MAX_EDGES,
    MAX_STATES,
    ValidationError,
    analyze,
    classify,
    validate,
)

__all__ = [
    "MAX_EDGES",
    "MAX_STATES",
    "ValidationError",
    "analyze",
    "classify",
    "validate",
]
