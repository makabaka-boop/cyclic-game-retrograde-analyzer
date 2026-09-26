"""Independent verification of the game graph analyzer.

The analyzer under test (:mod:`gamegraph.analyzer`) uses a worklist attractor,
Tarjan SCCs and BFS-DAG enumeration.  Nothing here reuses that machinery:

* statuses are recomputed by a naive monotone least-fixed-point iteration;
* "on a cycle" is recomputed by Floyd-Warshall reachability over the DRAW
  subgraph (a node is cyclic iff a non-empty path exists from it to itself);
* every WIN/LOSE witness edge is checked to exist in the input and match the
  contract's minimality/ordering requirements;
* DRAW witnesses are checked against brute-force enumeration of every shortest
  entry path and every simple cycle through the entry state.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from collections import deque
from itertools import product
from pathlib import Path

import pytest

from gamegraph import ValidationError, analyze
from gamegraph.analyzer import MAX_EDGES, MAX_STATES, classify, validate

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Independent reference solver (naive attractor fixed point)
# ---------------------------------------------------------------------------


def naive_classify(states, edges):
    """Least fixed point, recomputed from scratch each round."""
    succ = {s: set() for s in states}
    for src, dst in edges:
        succ[src].add(dst)
    win: set[str] = set()
    lose: set[str] = set()
    changed = True
    while changed:
        changed = False
        for s in states:
            if s in win or s in lose:
                continue
            if not succ[s]:
                lose.add(s)
                changed = True
            elif succ[s] & lose:  # some move hands the opponent a losing state
                win.add(s)
                changed = True
            elif succ[s] <= win:  # every move hands the opponent a winning state
                lose.add(s)
                changed = True
    draw = set(states) - win - lose
    return {s: ("WIN" if s in win else "LOSE" if s in lose else "DRAW") for s in states}


def draw_adjacency(draw, edges):
    dsucc = {s: set() for s in draw}
    for src, dst in edges:
        if src in draw and dst in draw:
            dsucc[src].add(dst)
    return {s: sorted(v) for s, v in dsucc.items()}


def naive_cyclic(nodes, dsucc):
    """Floyd-Warshall: v is cyclic iff there is a non-empty walk v -> ... -> v."""
    reach = {u: set(dsucc[u]) for u in nodes}
    for k in nodes:
        rk = reach[k]
        for i in nodes:
            if k in reach[i]:
                reach[i] |= rk
    return {v for v in nodes if v in reach[v]}


# ---------------------------------------------------------------------------
# Brute-force witness enumeration (shortest paths and simple cycles)
# ---------------------------------------------------------------------------


def all_shortest_paths(src, dst, dsucc):
    """Every shortest src->dst path, via BFS levels + DFS over the BFS DAG."""
    dist = {src: 0}
    frontier = [src]
    while frontier and dst not in dist:
        nxt = set()
        for u in frontier:
            for v in dsucc[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    nxt.add(v)
        frontier = list(nxt)
    if dst not in dist:
        return []
    paths: list[list[str]] = []

    def dfs(u, path):
        if u == dst:
            paths.append(list(path))
            return
        for v in dsucc[u]:
            if dist.get(v) == dist[u] + 1:
                path.append(v)
                dfs(v, path)
                path.pop()

    dfs(src, [src])
    return paths


def all_simple_cycles_through(entry, dsucc):
    """Every simple directed cycle through entry, rotated to min id.

    Depth-first search with entry forbidden as an interior vertex; a walk closes
    when the current vertex has an edge back to entry.  Self loops included.
    """
    found: set[tuple[str, ...]] = set()
    stack = [entry]
    on_path = {entry}

    def dfs(u):
        for v in dsucc[u]:
            if v == entry:
                walk = tuple(stack)
                n = len(walk)
                rotated = min(
                    walk[i:] + walk[:i] for i in range(n)
                )
                found.add(rotated)
            elif v not in on_path:
                stack.append(v)
                on_path.add(v)
                dfs(v)
                stack.pop()
                on_path.remove(v)

    dfs(entry)
    return found


def expected_draw_witness(query, draw, edges):
    """The contract's optimal (path, cycle) pair, found by full enumeration."""
    dsucc = draw_adjacency(draw, edges)
    cyclic = naive_cyclic(draw, dsucc)

    dist = {query: 0}
    frontier = [query]
    while frontier:
        nxt = set()
        for u in frontier:
            for v in dsucc[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    nxt.add(v)
        frontier = list(nxt)

    reachable_entries = cyclic & set(dist)
    assert reachable_entries, "every DRAW node must reach a DRAW cycle"
    entry_dist = min(dist[c] for c in reachable_entries)
    entries = [c for c in reachable_entries if dist[c] == entry_dist]

    best = None
    for entry in entries:
        cycles = all_simple_cycles_through(entry, dsucc)
        min_len = min(map(len, cycles))
        shortest_cycles = sorted(c for c in cycles if len(c) == min_len)
        for path in all_shortest_paths(query, entry, dsucc):
            assert path[-1] == entry
            for cycle in shortest_cycles:
                candidate = (tuple(path), entry, tuple(cycle))
                if best is None or candidate < best:
                    best = candidate
    return best


# ---------------------------------------------------------------------------
# Witness checking helpers
# ---------------------------------------------------------------------------


def verify_status_witnesses(result, edges):
    """Check every WIN move and every LOSE evidence list against raw edges."""
    edge_set = {tuple(e) for e in edges}
    succ = {sid: [] for sid in result["states"]}
    for src, dst in edges:
        succ[src].append(dst)
    for sid, succs in succ.items():
        succs.sort()

    for sid, info in result["states"].items():
        st = info["status"]
        if st == "WIN":
            witness = info["witness"]
            action = tuple(witness["action"])
            assert action in edge_set, f"WIN witness edge {action} does not exist"
            assert action[0] == sid
            assert witness["to"] == action[1]
            assert result["states"][witness["to"]]["status"] == "LOSE"
            assert witness["to_status"] == "LOSE"
            # smallest-id LOSE successor is required
            lose_succs = [t for t in succ[sid]
                          if result["states"][t]["status"] == "LOSE"]
            assert witness["to"] == min(lose_succs)
        elif st == "LOSE":
            ev = info["evidence"]
            assert ev["terminal"] == (not succ[sid])
            listed = [item["to"] for item in ev["all_successors_win"]]
            assert listed == succ[sid], "LOSE must list every successor, id-sorted"
            for item, target in zip(ev["all_successors_win"], succ[sid]):
                assert tuple(item["action"]) == (sid, target)
                assert item["to"] == target
                assert item["to_status"] == "WIN"
                assert result["states"][target]["status"] == "WIN"
        else:
            assert set(info) == {"status"}


def verify_query_witness(result, query, draw, edges):
    qres = result["queries"][query]
    status_by_id = {sid: info["status"] for sid, info in result["states"].items()}
    edge_set = {tuple(e) for e in edges}
    if status_by_id[query] != "DRAW":
        assert qres == {"status": status_by_id[query], "draw_witness": None}
        return

    wit = qres["draw_witness"]
    path, entry, cycle = wit["path"], wit["enters_cycle_at"], wit["cycle"]
    dsucc = draw_adjacency(draw, edges)

    # path: real edges, DRAW only, ends at the declared entry
    assert path[0] == query
    assert all(status_by_id[s] == "DRAW" for s in path)
    for a, b in zip(path, path[1:]):
        assert (a, b) in edge_set and b in dsucc[a]
    assert path[-1] == entry

    # cycle: distinct DRAW states connected by real edges, rotated to min id
    assert len(cycle) == len(set(cycle))
    assert cycle[0] == min(cycle)
    assert entry in cycle
    n = len(cycle)
    for i in range(n):
        a, b = cycle[i], cycle[(i + 1) % n]
        assert (a, b) in edge_set and b in dsucc[a]

    # exact optimality compared with independent brute-force enumeration
    exp_path, exp_entry, exp_cycle = expected_draw_witness(query, draw, edges)
    assert tuple(path) == exp_path, (path, exp_path)
    assert entry == exp_entry
    assert tuple(cycle) == exp_cycle, (cycle, exp_cycle)


def independent_can_reach_self(start, adj):
    """Does a non-empty directed walk from ``start`` return to itself?

    Plain BFS over successors, independently implemented (not Tarjan like the
    implementation under test).  Linear in graph size.
    """
    seen = set(adj[start])
    stack = list(adj[start])
    while stack:
        u = stack.pop()
        if u == start:
            return True
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return False


def independent_bfs_distance(adj, sources):
    """Multi-source unweighted distance, expanded in id order."""
    dist = {s: 0 for s in sources}
    frontier = deque(sorted(sources))
    while frontier:
        u = frontier.popleft()
        for v in sorted(adj[u]):
            if v not in dist:
                dist[v] = dist[u] + 1
                frontier.append(v)
    return dist


def independent_lex_shortest_to_cycle(adj, cyclic, dist):
    """Lexicographically smallest shortest walk from each node to the cyclic set.

    Independent DP by distance layer (not a BFS discovery-order replay)::

        label[c] = (c,)                              for cyclic c
        label[u] = min over eligible successors v of (u,) + label[v]
                   (eligible: dist[v] == dist[u] - 1)

    Processing nodes in increasing distance makes every successor label known.
    Comparing whole tuples resolves the tie between different cycle entries.
    """
    label: dict[str, tuple[str, ...]] = {c: (c,) for c in cyclic}
    layers: dict[int, list[str]] = {}
    for u, d in dist.items():
        layers.setdefault(d, []).append(u)
    for d in sorted(layers):
        if d == 0:
            continue
        for u in sorted(layers[d]):
            best = None
            for v in adj[u]:
                if dist.get(v) == d - 1:
                    cand = (u,) + label[v]
                    if best is None or cand < best:
                        best = cand
            assert best is not None
            label[u] = best
    return label


def verify_query_witness_structural(result, query, draw, edges):
    """Polynomial-time independent verification of a DRAW witness.

    It checks edge reality, the DRAW-only condition, shortest-path distance to
    the cycle set, the lexicographic minimality of the chosen path and that the
    returned cycle is a shortest simple closed walk through the entry.
    Global (path, entry, cycle) lexicographic tie-breaking is asserted exactly
    only by the small exhaustive tests; here each layer is checked separately.
    """
    status_by_id = {sid: info["status"] for sid, info in result["states"].items()}
    edge_set = {tuple(e) for e in edges}
    assert status_by_id[query] == "DRAW"

    wit = result["queries"][query]["draw_witness"]
    path = wit["path"]
    entry = wit["enters_cycle_at"]
    cycle = wit["cycle"]
    adj = draw_adjacency(draw, edges)

    # path: real edges, DRAW only, ends at the declared entry
    assert path[0] == query
    assert all(status_by_id[s] == "DRAW" for s in path)
    for a, b in zip(path, path[1:]):
        assert (a, b) in edge_set and b in adj[a]
    assert path[-1] == entry

    # the entry really lies on a directed cycle
    assert independent_can_reach_self(entry, adj)
    cyclic = {v for v in draw if independent_can_reach_self(v, adj)}

    # multi-source BFS runs BACKWARDS from the cyclic set along predecessors,
    # so build reversed DRAW adjacency explicitly
    reverse = {v: [] for v in draw}
    for u in draw:
        for v in adj[u]:
            reverse[v].append(u)
    dist_to_cycle = independent_bfs_distance(reverse, cyclic)
    assert query in dist_to_cycle, "every DRAW node must reach a DRAW cycle"
    assert len(path) - 1 == dist_to_cycle[query]

    # the path is the globally lex-smallest shortest route (independent DP),
    # including the choice of which cyclic node it enters
    labels = independent_lex_shortest_to_cycle(adj, cyclic, dist_to_cycle)
    assert tuple(path) == labels[query]
    assert entry == path[-1]

    # cycle: distinct DRAW states, real closing edges, rotated to min id
    assert len(cycle) == len(set(cycle))
    assert cycle[0] == min(cycle)
    assert entry in cycle
    for i in range(len(cycle)):
        a, b = cycle[i], cycle[(i + 1) % len(cycle)]
        assert (a, b) in edge_set and b in adj[a]

    # the cycle is a shortest simple closed walk through the entry:
    # multi-source BFS from the entry's successors (entry forbidden mid-walk)
    depth: dict[str, int] = {}
    q: deque[str] = deque()
    for v in adj[entry]:
        if v == entry:
            # self loop is the unique length-1 minimum
            assert cycle == [entry]
            return
        if v not in depth:
            depth[v] = 1
            q.append(v)
    min_close = None
    while q:
        u = q.popleft()
        if entry in adj[u]:
            min_close = depth[u]
            break
        if min_close is None:
            for v in adj[u]:
                if v != entry and v not in depth:
                    depth[v] = depth[u] + 1
                    q.append(v)
    assert min_close is not None
    # walk entry -> depth-1 node -> ... -> depth-k closer -> entry visits
    # k + 1 distinct states, and that count equals the cycle tuple length
    assert len(cycle) == min_close + 1


def run_analysis(states, edges, queries=None, thorough=True):
    payload = {"states": states, "edges": [[a, b] for a, b in edges]}
    if queries is not None:
        payload["queries"] = queries
    result = analyze(payload)
    expected = naive_classify(states, edges)
    got = {sid: info["status"] for sid, info in result["states"].items()}
    assert got == expected
    verify_status_witnesses(result, edges)
    draw = {s for s, st in expected.items() if st == "DRAW"}
    if queries is not None:
        for q in queries:
            if thorough:
                verify_query_witness(result, q, draw, edges)
            else:
                if got[q] == "DRAW":
                    verify_query_witness_structural(result, q, draw, edges)
                else:
                    assert result["queries"][q]["draw_witness"] is None
    return result, expected


# ---------------------------------------------------------------------------
# Fixed small graphs
# ---------------------------------------------------------------------------


def test_two_terminal_states_are_both_lose():
    result, expected = run_analysis(["a", "b"], [], ["a", "b"])
    assert expected == {"a": "LOSE", "b": "LOSE"}
    assert result["counts"] == {"WIN": 0, "LOSE": 2, "DRAW": 0}
    for sid in ("a", "b"):
        assert result["states"][sid]["evidence"]["terminal"] is True


def test_single_move_makes_winner_and_loser():
    result, expected = run_analysis(["a", "b"], [("a", "b")], ["a", "b"])
    assert expected == {"a": "WIN", "b": "LOSE"}
    assert result["states"]["a"]["witness"]["action"] == ["a", "b"]


def test_pure_three_cycle_is_draw():
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    result, expected = run_analysis(["a", "b", "c"], edges, ["a", "b", "c"])
    assert set(expected.values()) == {"DRAW"}
    for q in ("a", "b", "c"):
        wit = result["queries"][q]["draw_witness"]
        assert wit["path"] == [q]
        assert wit["cycle"] == ["a", "b", "c"]
        assert wit["enters_cycle_at"] == q


def test_self_loop_with_no_exit_is_draw():
    result, _ = run_analysis(["x", "y"], [("x", "x"), ("y", "x")], ["x", "y"])
    # x loops forever (DRAW); y can only move to a DRAW state -> DRAW too.
    assert result["states"]["x"]["status"] == "DRAW"
    assert result["states"]["y"]["status"] == "DRAW"
    wit = result["queries"]["x"]["draw_witness"]
    assert wit == {"path": ["x"], "enters_cycle_at": "x", "cycle": ["x"]}


def test_cycle_with_exit_to_win_stays_draw_while_forced_node_loses():
    # a<->b is a cycle; a also has an exit to w which is WIN (w->terminal t).
    # The exit is a bad move the player avoids, so a,b remain DRAW.  Forcing a
    # move to a WIN state loses: e->t makes e WIN, hence d->e makes d LOSE.
    edges = [("a", "b"), ("b", "a"), ("a", "w"), ("w", "t"),
             ("e", "t"), ("d", "e")]
    result, expected = run_analysis(
        ["a", "b", "w", "t", "d", "e"], edges, ["a", "b", "d", "e"]
    )
    assert expected["t"] == "LOSE"
    assert expected["w"] == expected["e"] == "WIN"
    assert expected["a"] == expected["b"] == "DRAW"
    assert expected["d"] == "LOSE"
    assert result["states"]["d"]["evidence"]["all_successors_win"] == [
        {"action": ["d", "e"], "to": "e", "to_status": "WIN"}
    ]
    for q in ("a", "b"):
        wit = result["queries"][q]["draw_witness"]
        assert wit["cycle"] == ["a", "b"]
        assert wit["path"] == [q]
        assert wit["enters_cycle_at"] == q


def test_win_witness_picks_smallest_losing_successor_id():
    # s has successors z,a (WIN) and m,q (LOSE): the witness must pick q, the
    # smallest id among the moves that force the opponent into LOSE.
    edges = [
        ("s", "z"), ("s", "m"), ("s", "a"), ("s", "q"),
        ("z", "tz"), ("a", "ta"),       # z,a are WIN (point at terminals)
        ("m", "mz"), ("mz", "mzz"),     # m is LOSE (its only successor is WIN)
        ("q", "qz"), ("qz", "qzz"),     # q is LOSE for the same reason
    ]
    states = ["s", "z", "m", "a", "q", "tz", "ta",
              "mz", "mzz", "qz", "qzz"]
    result, expected = run_analysis(states, edges)
    assert expected["s"] == "WIN"
    assert expected["m"] == expected["q"] == "LOSE"
    assert expected["z"] == expected["a"] == "WIN"
    assert result["states"]["s"]["witness"]["to"] == "m"
    assert result["states"]["s"]["witness"]["action"] == ["s", "m"]


def test_draw_path_lex_tiebreak_across_cycle_entries():
    # Regression: a multi-source BFS discovery order can promote a larger path
    # suffix.  From x, x->c->p and x->a->z are equally short routes to a cyclic
    # self loop; the id-lex comparison must choose (x, a, z).
    states = ["x", "a", "b", "c", "p", "z"]
    edges = [("c", "p"), ("a", "z"), ("b", "z"), ("x", "a"), ("x", "c"),
             ("p", "p"), ("z", "z")]
    result, expected = run_analysis(states, edges, ["x"], thorough=True)
    wit = result["queries"]["x"]["draw_witness"]
    assert wit["path"] == ["x", "a", "z"]
    assert wit["enters_cycle_at"] == "z"
    assert wit["cycle"] == ["z"]


def test_long_forced_chain():
    # 0 terminal LOSE, then WIN/LOSE alternating up the chain.
    states = [f"s{i}" for i in range(6)]
    edges = [(f"s{i+1}", f"s{i}") for i in range(5)]
    result, expected = run_analysis(states, edges, states)
    for i in range(6):
        assert expected[f"s{i}"] == "LOSE" if i % 2 == 0 else "WIN"
    assert result["states"]["s5"]["witness"]["action"] == ["s5", "s4"]


# ---------------------------------------------------------------------------
# Random graphs: exhaustive witness verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(60))
def test_random_small_graphs_exhaustive_witness_tiebreak(seed):
    """Tiny graphs: brute-force every shortest path and every simple cycle to
    assert the exact (shortest path, id-lex) ordering, cycles from min id."""
    rng = random.Random(2000 + seed)
    n = rng.randint(2, 6)
    states = [f"s{i}" for i in range(n)]
    edges = set()
    p = rng.choice([0.2, 0.4, 0.6, 0.9])
    for src, dst in product(states, repeat=2):
        if rng.random() < p:
            edges.add((src, dst))
    if seed % 3 == 0:  # force a terminal state sometimes
        edges = {(a, b) for a, b in edges if a != states[-1]}
    if seed % 4 == 0:  # force a two-cycle sometimes
        edges.add((states[0], states[1]))
        edges.add((states[1], states[0]))
    edges = sorted(edges)
    queries = list(states)
    rng.shuffle(queries)
    run_analysis(states, edges, queries, thorough=True)


@pytest.mark.parametrize("seed", range(30))
def test_random_medium_graphs_polynomial_verification(seed):
    """Larger/denser graphs would make cycle enumeration factorial; instead an
    independent polynomial verifier checks distances, witness edges and that
    the returned cycle is a shortest closed walk through its entry."""
    rng = random.Random(3000 + seed)
    n = rng.randint(7, 30)
    states = [f"s{i:02d}" for i in range(n)]
    edges = set()
    p = rng.choice([0.05, 0.15, 0.35, 0.6])
    for src, dst in product(states, repeat=2):
        if rng.random() < p:
            edges.add((src, dst))
    # guarantee variety: one terminal, one two-cycle, and a self loop
    edges = {(a, b) for a, b in edges if a != states[-1]}
    edges.add((states[0], states[1]))
    edges.add((states[1], states[0]))
    edges.add((states[n // 2], states[n // 2]))
    edges = sorted(edges)
    queries = states[:: max(1, n // 10)]
    run_analysis(states, edges, queries, thorough=False)


# ---------------------------------------------------------------------------
# Validation: the whole request is rejected
# ---------------------------------------------------------------------------


def rejection_errors(payload):
    with pytest.raises(ValidationError) as excinfo:
        analyze(payload)
    return excinfo.value.errors


def test_unknown_state_in_edge_rejected():
    errors = rejection_errors(
        {"states": ["a", "b"], "edges": [["a", "ghost"]]}
    )
    assert any("unknown state" in e and "ghost" in e for e in errors)


def test_duplicate_state_rejected():
    errors = rejection_errors({"states": ["a", "b", "a"], "edges": []})
    assert any("duplicate state" in e for e in errors)


def test_duplicate_edge_rejected():
    errors = rejection_errors(
        {"states": ["a", "b"], "edges": [["a", "b"], ["a", "b"]]}
    )
    assert any("duplicate edge" in e for e in errors)


def test_non_ascii_state_rejected():
    errors = rejection_errors({"states": ["a", "状态"], "edges": []})
    assert any("invalid state id" in e for e in errors)


def test_empty_and_non_string_states_rejected():
    errors = rejection_errors({"states": ["a", "", 3], "edges": []})
    assert any("invalid state id" in e for e in errors)
    assert len([e for e in errors if "invalid state id" in e]) == 2


def test_malformed_edge_rejected():
    errors = rejection_errors(
        {"states": ["a", "b"], "edges": [["a"], "ab", 4, ["a", "b", "c"]]}
    )
    assert sum("invalid edge" in e for e in errors) == 4


def test_too_many_states_rejected():
    payload = {"states": [f"s{i}" for i in range(MAX_STATES + 1)], "edges": []}
    assert any("between" in e for e in rejection_errors(payload))


def test_too_few_states_rejected():
    assert any("between" in e for e in rejection_errors({"states": ["lonely"]}))


def test_too_many_edges_rejected():
    # Build >2000 distinct edges by spreading over 300 states.
    states = [f"s{i:03d}" for i in range(300)]
    edges = []
    for i in range(300):
        for j in range(7):
            edges.append([states[i], states[(i + j) % 300]])
    assert len(edges) > MAX_EDGES
    payload = {"states": states, "edges": edges}
    assert any("at most" in e for e in rejection_errors(payload))


def test_unknown_query_rejected_but_duplicate_queries_allowed():
    errors = rejection_errors(
        {"states": ["a", "b"], "edges": [], "queries": ["a", "nope"]}
    )
    assert any("query references unknown state" in e for e in errors)
    result = analyze({"states": ["a", "b"], "edges": [], "queries": ["a", "a", "b"]})
    assert list(result["queries"]) == ["a", "b"]


def test_duplicate_edge_and_unknown_state_reported_together():
    errors = rejection_errors(
        {"states": ["a", "b", "a"],
         "edges": [["a", "ghost"], ["a", "ghost"], ["b", "phantom"]]}
    )
    assert any("duplicate state" in e for e in errors)
    assert any("duplicate edge" in e for e in errors)
    assert sum("unknown state" in e and "ghost" in e for e in errors) == 1
    assert any("phantom" in e for e in errors)


def test_not_an_object_rejected():
    with pytest.raises(ValidationError):
        analyze([1, 2, 3])


# ---------------------------------------------------------------------------
# Bounds and determinism at maximum size
# ---------------------------------------------------------------------------


def test_max_size_graph_performance_and_witnesses():
    rng = random.Random(42)
    states = [f"s{i:03d}" for i in range(MAX_STATES)]
    edge_set = set()
    while len(edge_set) < MAX_EDGES:
        i = rng.randrange(MAX_STATES)
        j = rng.randrange(MAX_STATES)
        edge_set.add((states[i], states[j]))
    edges = sorted(edge_set)
    payload = {"states": states, "edges": [list(e) for e in edges],
               "queries": states}
    start = time.perf_counter()
    result = analyze(payload)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0

    expected = naive_classify(states, edges)
    got = {sid: info["status"] for sid, info in result["states"].items()}
    assert got == expected
    verify_status_witnesses(result, edges)
    draw = {s for s, st in expected.items() if st == "DRAW"}
    dsucc = draw_adjacency(draw, edges)
    edge_set2 = set(edges)
    cycle_nodes_to_check: set[str] = set()
    for q in states:
        if expected[q] != "DRAW":
            assert result["queries"][q]["draw_witness"] is None
            continue
        wit = result["queries"][q]["draw_witness"]
        path, cycle = wit["path"], wit["cycle"]
        assert all(got[s] == "DRAW" for s in path)
        assert all(
            (path[i], path[i + 1]) in edge_set2 for i in range(len(path) - 1)
        )
        for i in range(len(cycle)):
            assert (cycle[i], cycle[(i + 1) % len(cycle)]) in edge_set2
        assert cycle[0] == min(cycle)
        cycle_nodes_to_check.update(cycle)
    # every reported cycle node genuinely reaches itself (independent BFS)
    for node in cycle_nodes_to_check:
        assert independent_can_reach_self(node, dsucc)


def test_result_is_deterministic():
    payload = {"states": ["a", "b", "c", "d"],
               "edges": [["a", "b"], ["b", "a"], ["a", "c"],
                         ["c", "d"], ["b", "d"]],
               "queries": ["a", "b"]}
    first = json.dumps(analyze(payload), sort_keys=True)
    second = json.dumps(analyze(json.loads(json.dumps(payload))), sort_keys=True)
    assert first == second


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


def run_cli(payload, *flags):
    proc = subprocess.run(
        [sys.executable, "-m", "gamegraph", *flags],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return proc


def test_cli_success_stdin():
    proc = run_cli({"states": ["a", "b"], "edges": [["a", "b"]],
                    "queries": ["a"]})
    assert proc.returncode == 0
    assert proc.stderr == ""
    result = json.loads(proc.stdout)
    assert result["states"]["a"]["status"] == "WIN"
    assert result["queries"]["a"]["status"] == "WIN"
    assert result["queries"]["a"]["draw_witness"] is None


def test_cli_rejection_exits_2_with_json_errors_on_stderr():
    proc = run_cli({"states": ["a"]})
    assert proc.returncode == 2
    assert proc.stdout == ""
    err = json.loads(proc.stderr)
    assert err["status"] == "error"
    assert err["errors"]


def test_cli_invalid_json_exits_2():
    proc = subprocess.run(
        [sys.executable, "-m", "gamegraph"],
        input="{not json",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        shell=False,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stderr)["status"] == "error"


def test_cli_file_argument_and_pretty_output(tmp_path):
    req = tmp_path / "req.json"
    req.write_text(json.dumps({"states": ["a", "b"], "edges": [["b", "a"]]}))
    proc = subprocess.run(
        [sys.executable, "-m", "gamegraph", "--pretty", str(req)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    assert "\n  \"status\": \"ok\"" in proc.stdout


# ---------------------------------------------------------------------------
# Internal unit checks
# ---------------------------------------------------------------------------


def test_classify_matches_naive_on_sample():
    states = ["a", "b", "c"]
    edges = [("a", "b"), ("b", "a"), ("b", "c")]
    from gamegraph.analyzer import build_adjacency
    succ, pred = build_adjacency(states, edges)
    assert classify(succ, pred, states) == naive_classify(states, edges)


def test_validate_dedupes_queries_in_first_seen_order():
    _, _, queries = validate(
        {"states": ["a", "b"], "edges": [], "queries": ["b", "a", "b"]}
    )
    assert queries == ["b", "a"]
