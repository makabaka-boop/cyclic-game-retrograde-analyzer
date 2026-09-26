"""DRAW witness shape: lasso path + rotated cycle, with tie-breaking."""

from __future__ import annotations

import random

from gamegraph import DRAW, GameGraph

from helpers import fixpoint_verdicts, verify_witness


def test_path_then_cycle():
    # q walks a tail into the {y, z} cycle.
    game = GameGraph(
        ["q", "x", "y", "z"],
        [("q", "x"), ("x", "y"), ("y", "z"), ("z", "y")],
    )
    assert all(game.verdict[s] == DRAW for s in game.states)
    assert game.draw_witness("q") == (["q", "x", "y"], ["y", "z"])


def test_self_loop_cycle():
    game = GameGraph(["q", "s"], [("q", "s"), ("s", "s")])
    assert game.draw_witness("q") == (["q", "s"], ["s"])
    assert game.draw_witness("s") == (["s"], ["s"])


def test_shortest_path_wins():
    # q can reach the cycle {c} directly (2 edges) or via b (3 edges).
    game = GameGraph(
        ["q", "a", "b", "c"],
        [("q", "a"), ("a", "c"), ("q", "b"), ("b", "a"), ("c", "c")],
    )
    assert game.draw_witness("q") == (["q", "a", "c"], ["c"])


def test_id_sequence_breaks_length_tie():
    # Both q->a->c and q->b->c reach the cycle in 2 edges; [q, a, c] wins.
    game = GameGraph(
        ["q", "a", "b", "c"],
        [("q", "b"), ("q", "a"), ("a", "c"), ("b", "c"), ("c", "c")],
    )
    assert game.draw_witness("q") == (["q", "a", "c"], ["c"])


def test_cycle_rotated_to_smallest_id():
    # Entry is c; the cycle c -> d -> b -> c keeps its cyclic order and is
    # reported starting at the smallest id, b: b -> c -> d -> (b).
    game = GameGraph(
        ["q", "b", "c", "d"],
        [("q", "c"), ("c", "d"), ("d", "b"), ("b", "c")],
    )
    path, cycle = game.draw_witness("q")
    assert path == ["q", "c"]
    assert cycle == ["b", "c", "d"]


def test_smallest_cycle_through_entry():
    # Two cycles through c: c->a->c and c->b->c; the id-smaller one wins.
    game = GameGraph(
        ["q", "a", "b", "c"],
        [("q", "c"), ("c", "a"), ("a", "c"), ("c", "b"), ("b", "c")],
    )
    path, cycle = game.draw_witness("q")
    assert path == ["q", "c"]
    assert cycle == ["a", "c"]


def test_random_graphs_match_fixpoint_and_brute_force():
    rng = random.Random(20260926)
    for _ in range(300):
        n = rng.randint(2, 10)
        states = [f"s{i}" for i in range(n)]
        all_edges = [(a, b) for a in states for b in states]
        rng.shuffle(all_edges)
        m = rng.randint(0, min(len(all_edges), 25))
        edges = all_edges[:m]

        game = GameGraph(states, edges)
        assert game.verdict == fixpoint_verdicts(states, edges)
        for s in states:
            verify_witness(game, s)
