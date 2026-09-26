"""Whole-input rejection: unknown references, duplicates, limit violations."""

from __future__ import annotations

import pytest

from gamegraph import InputError, parse_input
from gamegraph.model import MAX_EDGES, MAX_STATES

VALID = {"states": ["a", "b"], "edges": [{"from": "a", "to": "b"}]}


def bad(**patch):
    doc = {**VALID, **patch}
    for key, value in patch.items():
        if value is None:
            doc.pop(key, None)
    return doc


@pytest.mark.parametrize(
    ("doc", "fragment"),
    [
        (["not", "an", "object"], "must be an object"),
        ({"edges": []}, "missing required field 'states'"),
        (bad(unknown_field=1), "unknown top-level field"),
        (bad(states="ab"), "'states' must be a list"),
        (bad(states=["only"]), "between 2 and 300"),
        (bad(states=[f"s{i}" for i in range(MAX_STATES + 1)]), "between 2 and 300"),
        (bad(states=["a", 1]), "must be strings"),
        (bad(states=["a", ""]), "non-empty"),
        (bad(states=["a", "x" * 65]), "exceeds"),
        (bad(states=["a", "bé"]), "printable ASCII"),
        (bad(states=["a", "状"]), "printable ASCII"),
        (bad(states=["dup", "dup"]), "duplicate state id: 'dup'"),
        (bad(edges="nope"), "'edges' must be a list"),
        (bad(edges=[{"from": "a", "to": "b", "extra": 1}]), "exactly the keys"),
        (bad(edges=[{"from": "a"}]), "exactly the keys"),
        (bad(edges=[{"from": "a", "to": 2}]), "must be state id strings"),
        (bad(edges=[{"from": "a", "to": "ghost"}]), "unknown state 'ghost'"),
        (bad(edges=[{"from": "ghost", "to": "a"}]), "unknown state 'ghost'"),
        (
            bad(edges=[{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]),
            "duplicate edge: 'a' -> 'b'",
        ),
        (bad(queries="a"), "'queries' must be a list"),
        (bad(queries=[1]), "must be state id strings"),
        (bad(queries=["ghost"]), "query references unknown state 'ghost'"),
    ],
)
def test_rejected_inputs(doc, fragment):
    with pytest.raises(InputError, match=fragment):
        parse_input(doc)


def test_too_many_edges():
    states = [f"s{i}" for i in range(50)]
    edges = [{"from": a, "to": b} for a in states for b in states][: MAX_EDGES + 1]
    assert len(edges) == MAX_EDGES + 1
    with pytest.raises(InputError, match="at most 2000 edges"):
        parse_input({"states": states, "edges": edges})


def test_boundaries_accepted():
    # Exactly 300 states and 2000 edges is fine; edges and queries optional.
    states = [f"s{i:03d}" for i in range(MAX_STATES)]
    edges = [
        {"from": a, "to": b}
        for a in states
        for b in states
        if a != b
    ][:MAX_EDGES]
    assert len(edges) == MAX_EDGES
    spec = parse_input({"states": states, "edges": edges})
    assert len(spec.states) == MAX_STATES
    assert len(spec.edges) == MAX_EDGES
    assert spec.queries == ()

    spec = parse_input({"states": ["a", "b"]})
    assert spec.edges == ()


def test_self_loop_and_duplicate_queries_accepted():
    spec = parse_input(
        {
            "states": ["a", "b"],
            "edges": [{"from": "a", "to": "a"}],
            "queries": ["a", "a", "b"],
        }
    )
    assert spec.edges == (("a", "a"),)
    assert spec.queries == ("a", "a", "b")
