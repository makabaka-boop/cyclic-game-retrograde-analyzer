"""Retrograde WIN/LOSE/DRAW analysis for finite, potentially cyclic games.

The game graph is a directed graph.  At a state the player *must* follow one
outgoing edge; a state without outgoing edges is an immediate loss.  Play that
never terminates is a draw.

Statuses are the least fixed point of the winning/losing attractor:

* a state is **LOSE** when *all* of its successors are WIN
  (a terminal state vacuously satisfies this and seeds the propagation);
* a state is **WIN** when it has at least one LOSE successor;
* every state left over is **DRAW** — play can stay outside the attractor
  forever, i.e. it can reach and remain on a directed cycle of DRAW states.

Only standard-library modules are used.  ``analyze`` consumes and returns plain
JSON-serialisable Python objects; :mod:`gamegraph.cli` wraps it with JSON I/O.
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Any

# Request limits mandated by the service contract.
MIN_STATES = 2
MAX_STATES = 300
MAX_EDGES = 2000

sys.setrecursionlimit(max(sys.getrecursionlimit(), 10_000))


class ValidationError(ValueError):
    """The whole request is rejected.

    ``errors`` contains every problem that was detected so the caller can fix
    them all at once.
    """

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _is_ascii_id(value: Any) -> bool:
    """A state id is a non-empty ASCII-only string."""
    return isinstance(value, str) and len(value) >= 1 and value.isascii()


def validate(
    payload: Any,
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Validate a decoded JSON request.

    Returns ``(states, edges, queries)`` with edges as ``(source, target)``
    tuples in first-seen order and queries deduplicated in first-seen order.
    Raises :class:`ValidationError` listing every detected problem; the whole
    request is rejected on any such problem.
    """
    errors: list[str] = []

    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])

    raw_states = payload.get("states")
    raw_edges = payload.get("edges", [])
    raw_queries = payload.get("queries", [])

    # -- states -------------------------------------------------------------
    states: list[str] = []
    state_ids: set[str] = set()
    if "states" not in payload:
        errors.append("missing required field 'states'")
    elif not isinstance(raw_states, list):
        errors.append("'states' must be a list of state ids")
    else:
        if not (MIN_STATES <= len(raw_states) <= MAX_STATES):
            errors.append(
                f"'states' must contain between {MIN_STATES} and {MAX_STATES} entries, "
                f"got {len(raw_states)}"
            )
        invalid = sorted(
            {repr(x) for x in raw_states if not _is_ascii_id(x)}
        )
        for x in invalid:
            errors.append(
                f"invalid state id (must be a non-empty ASCII string): {x}"
            )
        seen: set[str] = set()
        duplicates: set[str] = set()
        for x in raw_states:
            if isinstance(x, str):
                if x in seen:
                    duplicates.add(x)
                seen.add(x)
        for x in sorted(duplicates):
            errors.append(f"duplicate state id: {x!r}")
        # Every well-formed string id is known for reference checking, even if
        # the list as a whole is rejected for duplicates/count; this lets us
        # report edge/query reference problems in the same rejection response.
        state_ids = {x for x in seen if _is_ascii_id(x)}
        if not invalid and not duplicates and MIN_STATES <= len(raw_states) <= MAX_STATES:
            states = list(raw_states)

    # -- edges --------------------------------------------------------------
    edges: list[tuple[str, str]] = []
    if not isinstance(raw_edges, list):
        errors.append("'edges' must be a list of [source, target] pairs")
    else:
        if len(raw_edges) > MAX_EDGES:
            errors.append(
                f"'edges' may contain at most {MAX_EDGES} entries, got {len(raw_edges)}"
            )
        malformed: list[str] = []
        edge_seen: set[tuple[str, str]] = set()
        edge_dup: set[tuple[str, str]] = set()
        ordered: list[tuple[str, str]] = []
        for edge in raw_edges:
            if (
                not isinstance(edge, list)
                or len(edge) != 2
                or not all(isinstance(x, str) for x in edge)
            ):
                if len(malformed) < 20:
                    malformed.append(repr(edge))
                continue
            pair = (edge[0], edge[1])
            if pair in edge_seen:
                edge_dup.add(pair)
            else:
                edge_seen.add(pair)
                ordered.append(pair)
        for x in malformed:
            errors.append(
                f"invalid edge (must be a [source, target] pair of strings): {x}"
            )
        for pair in sorted(edge_dup):
            errors.append(f"duplicate edge: {[pair[0], pair[1]]!r}")

        references_ok = True
        if state_ids and len(raw_edges) <= MAX_EDGES:
            unknown: set[str] = set()
            for src, dst in edge_seen:
                if src not in state_ids:
                    unknown.add(src)
                if dst not in state_ids:
                    unknown.add(dst)
            for x in sorted(unknown):
                errors.append(f"edge references unknown state: {x!r}")
            references_ok = not unknown
        if (
            state_ids
            and not malformed
            and not edge_dup
            and references_ok
            and len(raw_edges) <= MAX_EDGES
        ):
            edges = ordered

    # -- queries ------------------------------------------------------------
    queries: list[str] = []
    if not isinstance(raw_queries, list):
        errors.append("'queries' must be a list of state ids")
    elif state_ids:
        q_seen: set[str] = set()
        for q in raw_queries:
            if not isinstance(q, str):
                errors.append(f"invalid query (must be a string): {q!r}")
            elif q not in state_ids:
                errors.append(f"query references unknown state: {q!r}")
            elif q not in q_seen:
                # Repeated queries are harmless: answer once in first-seen order.
                q_seen.add(q)
                queries.append(q)

    if errors:
        raise ValidationError(errors)
    return states, edges, queries


# ---------------------------------------------------------------------------
# Retrograde attractor
# ---------------------------------------------------------------------------


def build_adjacency(
    states: Iterable[str], edges: Iterable[tuple[str, str]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build sorted successor/predecessor adjacency lists."""
    succ: dict[str, list[str]] = {s: [] for s in states}
    pred: dict[str, list[str]] = {s: [] for s in states}
    for src, dst in edges:
        succ[src].append(dst)
        pred[dst].append(src)
    for adj in (succ, pred):
        for s in adj:
            adj[s].sort()
    return succ, pred


def classify(
    succ: dict[str, list[str]],
    pred: dict[str, list[str]],
    states: list[str],
) -> dict[str, str]:
    """Compute the WIN/LOSE/DRAW partition by retrograde propagation.

    The queue implements the standard attractor fixed point:

    * terminal states (no successors) start LOSE;
    * when a state becomes LOSE every predecessor becomes WIN;
    * a state becomes LOSE once *all* of its successors are known WIN
      (a successor counter tracks how many remain unclassified).

    States never reached by either rule are DRAW.  The worklist order does not
    affect the final partition, only its convergence speed.
    """
    status: dict[str, str | None] = {s: None for s in states}
    remaining = {s: len(succ[s]) for s in states}
    queue: deque[str] = deque()

    for s in states:
        if not succ[s]:
            status[s] = "LOSE"
            queue.append(s)

    while queue:
        v = queue.popleft()
        if status[v] == "LOSE":
            # Every predecessor that can move here forces a win.
            for u in pred[v]:
                if status.get(u) is None:
                    status[u] = "WIN"
                    queue.append(u)
        # v is now resolved (WIN or LOSE); any predecessor still waiting to be
        # LOSE has one fewer non-WIN successor.  WIN resolution of v is exactly
        # the event counted by ``remaining`` (LOSE successors short-circuit to
        # WIN and never wait).
        for u in pred[v]:
            if status.get(u) is None:
                remaining[u] -= 1
                if remaining[u] == 0:
                    status[u] = "LOSE"
                    queue.append(u)

    for s in states:
        if status.get(s) is None:
            status[s] = "DRAW"
    return status  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# DRAW subgraph: cyclic nodes, distances and lex-smallest witnesses
# ---------------------------------------------------------------------------


def _cyclic_nodes(nodes: set[str], succ: dict[str, list[str]]) -> set[str]:
    """Return nodes that lie on a directed cycle, found with Tarjan SCCs."""
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cyclic: set[str] = set()
    counter = 0

    def strongconnect(v: str) -> None:
        nonlocal counter
        indices[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)

        for w in succ[v]:
            if w not in indices:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])

        if low[v] == indices[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1 or v in succ[v]:
                cyclic.update(component)

    for v in nodes:
        if v not in indices:
            strongconnect(v)
    return cyclic


def _draw_structure(
    draw: set[str], succ: dict[str, list[str]]
) -> tuple[set[str], dict[str, list[str]], dict[str, int], dict[str, str]]:
    """Return ``(cyclic, draw_successors, distance, lex_parent)`` for DRAW nodes.

    ``distance`` is computed with a multi-source BFS run *backwards* from every
    cyclic node along DRAW-only edges; every DRAW node reaches the attractor's
    complement cycle so every distance is finite.

    ``lex_parent`` selects the globally lexicographically smallest shortest
    walk from each node to *some* cyclic node.  A plain first-discovery BFS is
    insufficient when multiple cycle entries tie: the order in which the
    cyclic sources are expanded can promote a larger suffix.  Instead, after
    distances are known, layers are processed from the cyclic set outwards and
    each node's suffix is given a dense *rank* that orders suffixes exactly as
    their state-id tuples compare.  For nodes u, v in one layer the suffix
    tuples compare first on the head id and then on the tail rank, i.e. the
    ordering key is ``(u, tail_rank)``.  Each node chooses the distance-
    decreasing successor whose suffix rank is minimal.
    """
    dsucc = {s: [t for t in succ[s] if t in draw] for s in draw}
    cyclic = _cyclic_nodes(draw, dsucc)

    dpred: dict[str, list[str]] = {s: [] for s in draw}
    for u in sorted(draw):
        for v in dsucc[u]:
            dpred[v].append(u)

    distance = {s: 0 for s in cyclic}
    queue: deque[str] = deque(cyclic)
    while queue:
        v = queue.popleft()
        for u in dpred[v]:  # lists are id-sorted
            if u not in distance:
                distance[u] = distance[v] + 1
                queue.append(u)

    # Layer-wise suffix ranks -> lexicographic parents.
    #
    # A node u's suffix is the tuple (u, tail(u)).  For two nodes u, v in the
    # same layer the suffixes compare *first on the head ids* and only then on
    # the tails, so the ordering key is (u, rank_of_chosen_successor) — not the
    # other way round.  Ranks are dense and layer-local; layer d-1 tails are
    # already ordered by the previous iteration.
    rank: dict[str, tuple[str, int]] = {s: (s, -1) for s in cyclic}
    layers: dict[int, list[str]] = {}
    for u, d in distance.items():
        layers.setdefault(d, []).append(u)
    parent_choice: dict[str, str] = {}
    for d in range(1, max(layers, default=0) + 1):
        best_key: dict[str, tuple[str, int]] = {}
        for u in layers[d]:
            best_succ = min(
                (t for t in dsucc[u] if distance.get(t) == d - 1),
                key=lambda t: rank[t],
            )
            parent_choice[u] = best_succ
            best_key[u] = (u, rank[best_succ][1])
        order = sorted(layers[d], key=lambda u: best_key[u])
        prev_key: tuple[str, int] | None = None
        r = -1
        for u in order:
            key = best_key[u]
            if key != prev_key:
                r += 1
                prev_key = key
            rank[u] = (u, r)

    return cyclic, dsucc, distance, parent_choice


def _min_rotation(cycle: tuple[str, ...]) -> tuple[str, ...]:
    """Rotate a simple cycle so it starts at its smallest state id."""
    n = len(cycle)
    return min(cycle[i:] + cycle[:i] for i in range(n))


# Maximum number of candidate shortest-cycle walks materialised while resolving
# the "cycle starts at the smallest id" tie-break.  Exact enumeration is linear
# on normal game graphs; only adversarially layered complete graphs have
# exponentially many shortest cycles (choosing the lex-min shortest cycle
# through a fixed vertex is NP-hard in general directed graphs), beyond this
# budget a valid shortest cycle is still always returned.
_CYCLE_WALK_CAP = 200_000


def _best_cycle(entry: str, dsucc: dict[str, list[str]]) -> list[str]:
    """Shortest simple cycle through ``entry`` rotated to its smallest id.

    A multi-source BFS from the successors of ``entry`` (``entry`` itself is
    forbidden as an interior node) defines a BFS DAG: every shortest return to
    ``entry`` is a depth-strict, hence simple, walk in that DAG.  The
    lexicographic winner after rotation is found by enumerating the shortest
    walks layer by layer; a global budget bounds the (theoretically
    exponential) work, with a polynomial rank-based fallback afterwards.
    """
    # Self loop is the unique length-1 cycle.
    if entry in dsucc[entry]:
        return [entry]

    depth: dict[str, int] = {}
    queue: deque[str] = deque()
    for source in dsucc[entry]:  # adjacency is id-sorted
        if source not in depth:
            depth[source] = 1
            queue.append(source)

    min_depth: int | None = None
    closers: list[str] = []
    while queue:
        u = queue.popleft()
        if min_depth is not None and depth[u] > min_depth:
            break
        if entry in dsucc[u]:
            if min_depth is None:
                min_depth = depth[u]
            closers.append(u)
        if min_depth is None or depth[u] < min_depth:
            for nxt in dsucc[u]:
                if nxt != entry and nxt not in depth:
                    depth[nxt] = depth[u] + 1
                    queue.append(nxt)
    assert min_depth is not None, "a DRAW cycle entry must lie on a cycle"

    incoming: dict[str, list[str]] = {node: [] for node in depth}
    for p in depth:
        for c in dsucc[p]:
            if c in depth and depth[c] == depth[p] + 1:
                incoming[c].append(p)

    layers: dict[int, list[str]] = {}
    for node, d in depth.items():
        layers.setdefault(d, []).append(node)

    walks: dict[str, list[tuple[str, ...]]] = {
        node: [(entry, node)] for node in layers.get(1, [])
    }
    total = len(walks)
    capped = False
    for d in range(2, min_depth + 1):
        for node in layers[d]:
            merged: set[tuple[str, ...]] = set()
            for p in incoming[node]:
                for walk in walks.get(p, ()):
                    merged.add(walk + (node,))
                    if total + len(merged) >= _CYCLE_WALK_CAP:
                        capped = True
                        break
                if capped:
                    break
            ordered = sorted(merged)
            if total + len(ordered) > _CYCLE_WALK_CAP:
                ordered = ordered[: max(0, _CYCLE_WALK_CAP - total)]
                capped = True
            walks[node] = ordered
            total += len(ordered)

    best: tuple[str, ...] | None = None
    for closer in closers:
        for walk in walks.get(closer, ()):
            rotated = _min_rotation(walk)
            if best is None or rotated < best:
                best = rotated

    if capped or best is None:
        # Polynomial fallback: dense forward ranks on the BFS DAG pick one
        # lex-consistent shortest walk per closer; take the best rotation.
        rank: dict[str, tuple[str, int]] = {
            node: (node, -1) for node in layers.get(1, [])
        }
        parent_choice: dict[str, str] = {}
        for d in range(2, min_depth + 1):
            keys: dict[str, tuple[str, int]] = {}
            for node in layers[d]:
                best_parent = min(incoming[node], key=lambda c: rank[c])
                parent_choice[node] = best_parent
                keys[node] = (node, rank[best_parent][1])
            ordered_nodes = sorted(layers[d], key=lambda x: keys[x])
            prev_key: tuple[str, int] | None = None
            r = -1
            for node in ordered_nodes:
                key = keys[node]
                if key != prev_key:
                    r += 1
                    prev_key = key
                rank[node] = (node, r)
        for closer in closers:
            chain = [closer]
            while depth[chain[-1]] > 1:
                chain.append(parent_choice[chain[-1]])
            chain.reverse()
            rotated = _min_rotation(tuple([entry] + chain))
            if best is None or rotated < best:
                best = rotated

    return list(best)  # type: ignore[arg-type]


def _draw_witness(
    query: str,
    dsucc: dict[str, list[str]],
    distance: dict[str, int],
    lex_parent: dict[str, str],
    cycle_cache: dict[str, list[str]],
) -> dict[str, list[str] | str]:
    """Build the shortest, id-lexicographically smallest DRAW witness.

    Following ``lex_parent`` (the layer-wise suffix-rank choice from
    :func:`_draw_structure`) walks the globally lex-smallest shortest route to
    the cyclic set, choosing the winning cycle entry automatically when several
    entries are equally close.  It ends on a cyclic node; the returned cycle is
    rotated to begin at its smallest state id.
    """
    path = [query]
    u = query
    while distance[u] > 0:
        u = lex_parent[u]
        path.append(u)
    entry = u
    if entry not in cycle_cache:
        cycle_cache[entry] = _best_cycle(entry, dsucc)
    return {
        "path": path,
        "enters_cycle_at": entry,
        "cycle": cycle_cache[entry],
    }


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------


def analyze(payload: Any) -> dict[str, Any]:
    """Validate ``payload`` and return the full analysis result.

    See the project README for the exact JSON contract; raises
    :class:`ValidationError` when the request must be rejected.
    """
    states, edges, queries = validate(payload)
    succ, pred = build_adjacency(states, edges)
    status = classify(succ, pred, states)

    draw = {s for s in states if status[s] == "DRAW"}
    if draw:
        _, dsucc, distance, lex_parent = _draw_structure(draw, succ)
    else:
        dsucc, distance, lex_parent = {}, {}, {}
    cycle_cache: dict[str, list[str]] = {}

    result_states: dict[str, Any] = {}
    counts = {"WIN": 0, "LOSE": 0, "DRAW": 0}
    for s in states:
        counts[status[s]] += 1
        entry: dict[str, Any] = {"status": status[s]}
        if status[s] == "WIN":
            # succ[s] is id-sorted, so the first LOSE successor has the
            # smallest target id — the forced move required by the contract.
            target = next(t for t in succ[s] if status[t] == "LOSE")
            entry["witness"] = {
                "action": [s, target],
                "to": target,
                "to_status": "LOSE",
            }
        elif status[s] == "LOSE":
            entry["evidence"] = {
                "terminal": not succ[s],
                "all_successors_win": [
                    {
                        "action": [s, t],
                        "to": t,
                        "to_status": status[t],
                    }
                    for t in succ[s]
                ],
            }
        result_states[s] = entry

    result: dict[str, Any] = {
        "status": "ok",
        "state_count": len(states),
        "edge_count": len(edges),
        "counts": counts,
        "states": result_states,
    }

    if "queries" in payload:
        query_results: dict[str, Any] = {}
        for q in queries:
            if status[q] == "DRAW":
                query_results[q] = {
                    "status": "DRAW",
                    "draw_witness": _draw_witness(
                        q, dsucc, distance, lex_parent, cycle_cache
                    ),
                }
            else:
                query_results[q] = {"status": status[q], "draw_witness": None}
        result["queries"] = query_results

    return result
