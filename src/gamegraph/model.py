"""Input model and strict validation.

Any violation rejects the whole input: the CLI reports the error as JSON on
stderr and exits with a non-zero status; nothing is analyzed.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_STATES = 2
MAX_STATES = 300
MAX_EDGES = 2000
MAX_STATE_LEN = 64

_TOP_LEVEL_FIELDS = frozenset({"states", "edges", "queries"})
_EDGE_FIELDS = frozenset({"from", "to"})


class InputError(Exception):
    """The input document is invalid and must be rejected as a whole."""


@dataclass(frozen=True)
class GameInput:
    """A validated analysis request.

    states: unique printable-ASCII state ids, in input order.
    edges:  unique (from, to) pairs, both endpoints known states.
    queries: states (possibly repeated) for which a full witness is wanted.
    """

    states: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    queries: tuple[str, ...]


def parse_input(data: object) -> GameInput:
    """Validate a decoded JSON document, raising InputError on any problem."""
    if not isinstance(data, dict):
        raise InputError("top-level JSON value must be an object")
    unknown = sorted(set(data) - _TOP_LEVEL_FIELDS)
    if unknown:
        raise InputError(f"unknown top-level field(s): {', '.join(unknown)}")
    if "states" not in data:
        raise InputError("missing required field 'states'")
    states = _parse_states(data["states"])
    known = frozenset(states)
    edges = _parse_edges(data.get("edges", []), known)
    queries = _parse_queries(data.get("queries", []), known)
    return GameInput(states=states, edges=edges, queries=queries)


def _parse_states(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise InputError("'states' must be a list of state id strings")
    if not MIN_STATES <= len(raw) <= MAX_STATES:
        raise InputError(
            f"'states' must contain between {MIN_STATES} and {MAX_STATES} "
            f"unique ids, got {len(raw)}"
        )
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        if not isinstance(s, str):
            raise InputError(f"state ids must be strings, got {s!r}")
        if not s:
            raise InputError("state ids must be non-empty")
        if len(s) > MAX_STATE_LEN:
            raise InputError(f"state id {s!r} exceeds {MAX_STATE_LEN} characters")
        if not all(0x20 <= ord(ch) <= 0x7E for ch in s):
            raise InputError(f"state id {s!r} must be printable ASCII")
        if s in seen:
            raise InputError(f"duplicate state id: {s!r}")
        seen.add(s)
        out.append(s)
    return tuple(out)


def _parse_edges(raw: object, known: frozenset[str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        raise InputError("'edges' must be a list of {\"from\", \"to\"} objects")
    if len(raw) > MAX_EDGES:
        raise InputError(f"at most {MAX_EDGES} edges allowed, got {len(raw)}")
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for e in raw:
        if not isinstance(e, dict) or set(e) != _EDGE_FIELDS:
            raise InputError(
                "each edge must be an object with exactly the keys 'from' and 'to'"
            )
        a, b = e["from"], e["to"]
        if not isinstance(a, str) or not isinstance(b, str):
            raise InputError("edge endpoints must be state id strings")
        if a not in known:
            raise InputError(f"edge references unknown state {a!r}")
        if b not in known:
            raise InputError(f"edge references unknown state {b!r}")
        if (a, b) in seen:
            raise InputError(f"duplicate edge: {a!r} -> {b!r}")
        seen.add((a, b))
        out.append((a, b))
    return tuple(out)


def _parse_queries(raw: object, known: frozenset[str]) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise InputError("'queries' must be a list of state id strings")
    out: list[str] = []
    for q in raw:
        if not isinstance(q, str):
            raise InputError(f"queries must be state id strings, got {q!r}")
        if q not in known:
            raise InputError(f"query references unknown state {q!r}")
        out.append(q)
    return tuple(out)
