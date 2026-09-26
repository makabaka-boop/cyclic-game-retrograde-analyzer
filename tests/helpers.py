"""Independent reference implementations used to cross-check the package.

Nothing here imports gamegraph.solver: the attractor fixpoint and the
brute-force lasso enumeration are deliberately written from the problem
statement so the tests are a genuine second opinion.
"""

from __future__ import annotations

WIN = "WIN"
LOSE = "LOSE"
DRAW = "DRAW"


def successors(states, edges):
    succ = {s: [] for s in states}
    for a, b in edges:
        succ[a].append(b)
    return succ


def fixpoint_verdicts(states, edges):
    """Least-fixpoint attractor computation, iterated to stability."""
    succ = successors(states, edges)
    win: set[str] = set()
    lose: set[str] = set()
    while True:
        new_win = {s for s in states if any(t in lose for t in succ[s])}
        new_lose = {
            s for s in states if not succ[s] or all(t in win for t in succ[s])
        }
        if new_win == win and new_lose == lose:
            break
        win, lose = new_win, new_lose
    return {
        s: WIN if s in win else LOSE if s in lose else DRAW for s in states
    }


def oncycle_states(states, edges, draw):
    """DRAW states from which the state itself is reachable in >= 1 edge,
    staying inside the DRAW subgraph."""
    succ = successors(states, edges)
    draw = set(draw)
    on = set()
    for s in draw:
        seen = set()
        stack = [t for t in succ[s] if t in draw]
        while stack:
            x = stack.pop()
            if x == s:
                on.add(s)
                break
            if x not in seen:
                seen.add(x)
                stack.extend(t for t in succ[x] if t in draw)
    return on


def brute_best_path(states, edges, draw, start):
    """Min (edge count, id sequence) simple path from ``start`` to a state on
    a DRAW-only cycle, by exhaustive enumeration of simple paths."""
    succ = successors(states, edges)
    draw = set(draw)
    oncycle = oncycle_states(states, edges, draw)
    best = None
    stack = [[start]]
    while stack:
        path = stack.pop()
        u = path[-1]
        if u in oncycle:
            key = (len(path) - 1, tuple(path))
            if best is None or key < best[0]:
                best = (key, path)
            continue
        for v in succ[u]:
            if v in draw and v not in path:
                stack.append(path + [v])
    assert best is not None, "DRAW state must reach a cycle"
    return best[1]


def brute_best_cycle(states, edges, draw, entry):
    """Min (edge count, id sequence from entry) simple directed cycle through
    ``entry``, by exhaustive enumeration; returned rotated to smallest id."""
    succ = successors(states, edges)
    draw = set(draw)
    best = None
    stack = [[entry]]
    while stack:
        path = stack.pop()
        u = path[-1]
        for v in succ[u]:
            if v not in draw:
                continue
            if v == entry:
                key = (len(path), tuple(path))
                if best is None or key < best[0]:
                    best = (key, path)
            elif v not in path:
                stack.append(path + [v])
    assert best is not None, "on-cycle state must have a cycle"
    cycle = best[1]
    i = min(range(len(cycle)), key=lambda k: cycle[k])
    return cycle[i:] + cycle[:i]


def verify_witness(game, state):
    """Check every witness edge and every optimality claim for one state."""
    verdict = game.verdict[state]
    if verdict == WIN:
        t = game.win_move(state)
        assert (state, t) in game.edges
        assert game.verdict[t] == LOSE
        lose_succs = [x for x in game.succ[state] if game.verdict[x] == LOSE]
        assert lose_succs, "WIN state must have a LOSE successor"
        assert t == min(lose_succs)
    elif verdict == LOSE:
        evidence = game.lose_evidence(state)
        assert list(evidence) == sorted(game.succ[state])
        assert len(evidence) == len(set(evidence))
        for t in evidence:
            assert (state, t) in game.edges
            assert game.verdict[t] == WIN
    else:
        path, cycle = game.draw_witness(state)
        edge_set = set(game.edges)
        # Path: starts at the query, simple, DRAW-only, real edges.
        assert path[0] == state
        assert len(set(path)) == len(path)
        assert all(game.verdict[x] == DRAW for x in path)
        for a, b in zip(path, path[1:]):
            assert (a, b) in edge_set
        # Cycle: genuine directed cycle, DRAW-only, smallest id first.
        assert cycle
        assert len(set(cycle)) == len(cycle)
        assert all(game.verdict[x] == DRAW for x in cycle)
        for i in range(len(cycle)):
            assert (cycle[i], cycle[(i + 1) % len(cycle)]) in edge_set
        assert cycle[0] == min(cycle)
        # The path enters the reported cycle only at its end.
        assert path[-1] in cycle
        assert set(path[:-1]).isdisjoint(cycle)
        # Optimality, checked against exhaustive enumeration.
        draw = [s for s in game.states if game.verdict[s] == DRAW]
        assert path == brute_best_path(game.states, game.edges, draw, state)
        entry = path[-1]
        assert cycle == brute_best_cycle(
            game.states, game.edges, draw, entry
        )
