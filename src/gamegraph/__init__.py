"""gamegraph — retrograde WIN/LOSE/DRAW analysis of finite directed game graphs."""

from .model import GameInput, InputError, parse_input
from .solver import DRAW, LOSE, WIN, GameGraph

__version__ = "1.0.0"

__all__ = [
    "DRAW",
    "LOSE",
    "WIN",
    "GameGraph",
    "GameInput",
    "InputError",
    "parse_input",
    "__version__",
]
