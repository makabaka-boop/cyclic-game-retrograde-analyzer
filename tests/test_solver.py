"""Solver semantics: retrograde verdicts and witnesses on hand-built graphs."""

from __future__ import annotations

from gamegraph import DRAW, LOSE, WIN, GameGraph

from helpers import fixpoint_verdicts, verify_witness


def check(states, edges, expected):
    game = GameGraph(states, edges)
    assert game.verdict == expected
    # The independent attractor fixpoint must agree.
    assert fixpoint_verdicts(states, edges) == game.verdict
    for s in states:
        verify_witness(game, s)
    return game


def test_single_move_to_terminal():
    check(["a", "b"], [("a", "b")], {"a": WIN, "b": LOSE})


def test_terminal_lose_has_empty_evidence():
    game = check(["a", "b"], [("a", "b")], {"a": WIN, "b": LOSE})
    assert game.lose_evidence("b") == ()


def test_both_terminal():
    check(["a", "b"], [], {"a": LOSE, "b": LOSE})


def test_self_loop_is_draw():
    # x can loop forever; y is a dead end.
    check(["x", "y"], [("x", "x")], {"x": DRAW, "y": LOSE})


def test_two_cycle_is_draw():
    check(
        ["a", "b"],
        [("a", "b"), ("b", "a")],
        {"a": DRAW, "b": DRAW},
    )


def test_cycle_with_exit_to_terminal():
    # b can move to the terminal c, so b is WIN; a can only move to b, so
    # a is LOSE; c is a dead end.  Both a and c are LOSE, so b's winning
    # move is the smaller id: a.
    game = check(
        ["a", "b", "c"],
        [("a", "b"), ("b", "a"), ("b", "c")],
        {"a": LOSE, "b": WIN, "c": LOSE},
    )
    assert game.win_move("b") == "a"
    assert game.lose_evidence("a") == ("b",)


def test_lose_requires_all_successors_win():
    # x moves only to w1/w2, both of which move to the terminal t.
    game = check(
        ["x", "w1", "w2", "t"],
        [("x", "w1"), ("x", "w2"), ("w1", "t"), ("w2", "t")],
        {"x": LOSE, "w1": WIN, "w2": WIN, "t": LOSE},
    )
    assert game.lose_evidence("x") == ("w1", "w2")


def test_win_move_picks_smallest_id():
    # s can reach LOSE states m, w, z (w is LOSE because its only move is
    # back to the WIN state s); the chosen move must be the smallest id.
    game = check(
        ["s", "m", "w", "z"],
        [("s", "z"), ("s", "m"), ("s", "w"), ("w", "s")],
        {"s": WIN, "m": LOSE, "w": LOSE, "z": LOSE},
    )
    assert game.win_move("s") == "m"


def test_draw_chain_not_misjudged_as_lose():
    # A plain win/lose recursion without cycle handling would call every
    # state here LOSE; everything is actually DRAW.
    check(
        ["a", "b", "c"],
        [("a", "b"), ("b", "c"), ("c", "c")],
        {"a": DRAW, "b": DRAW, "c": DRAW},
    )


def test_mixed_graph():
    # t: terminal LOSE.  w: WIN via t.  x: only to w -> LOSE.
    # d1/d2: a DRAW cycle.  y: to w (WIN) or d1 (DRAW) -> DRAW.
    game = check(
        ["t", "w", "x", "d1", "d2", "y"],
        [
            ("w", "t"),
            ("x", "w"),
            ("d1", "d2"),
            ("d2", "d1"),
            ("y", "w"),
            ("y", "d1"),
        ],
        {"t": LOSE, "w": WIN, "x": LOSE, "d1": DRAW, "d2": DRAW, "y": DRAW},
    )
    assert game.win_move("w") == "t"
    assert game.draw_witness("y") == (["y", "d1"], ["d1", "d2"])
