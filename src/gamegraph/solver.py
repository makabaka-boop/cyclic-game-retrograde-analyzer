"""Retrograde (backward-propagation) analysis of finite directed game graphs.

Rules of the game
-----------------
The player to move at state ``s`` must follow exactly one outgoing edge.
A state with no outgoing edge is an immediate LOSE for the player to move.
A play that never terminates is a DRAW.

Verdicts
--------
* LOSE — no outgoing edge, or every outgoing edge leads to a WIN state.
* WIN  — at least one outgoing edge leads to a LOSE state.
* DRAW — everything else: the player to move can avoid losing forever but
  cannot force the opponent into a LOSE state.

Id ordering
-----------
A state's *id* is its name string; ids are ordered by ASCII (code-point)
comparison.  All "smallest id" tie-breaks below use that order.

DRAW witnesses
--------------
For a DRAW state ``q`` the witness is a lasso inside the DRAW-only subgraph:
a simple path ``q .. c`` plus a genuine directed cycle through the entry
state ``c``.  The path is minimal by (number of edges, state-id sequence);
among the simple cycles through ``c`` the one minimal by (number of edges,
state-id sequence starting at ``c``) is chosen, and it is reported rotated
so that its smallest-id state comes first.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable

WIN = "WIN"
LOSE = "LOSE"
DRAW = "DRAW"


class GameGraph:
    """A finite directed game graph with retrograde verdicts for every state."""

    def __init__(
        self,
        states: Iterable[str],
        edges: Iterable[tuple[str, str]],
    ) -> None:
        self.states: tuple[str, ...] = tuple(sorted(states))
        succ: dict[str, list[str]] = {s: [] for s in self.states}
        pred: dict[str, list[str]] = {s: [] for s in self.states}
        for a, b in edges:
            succ[a].append(b)
            pred[b].append(a)
        # Successors/predecessors are kept sorted by id so that "smallest id"
        # selections are plain first-hits.
        self.succ: dict[str, tuple[str, ...]] = {
            s: tuple(sorted(v)) for s, v in succ.items()
        }
        self.pred: dict[str, tuple[str, ...]] = {
            s: tuple(sorted(v)) for s, v in pred.items()
        }
        self.edges: frozenset[tuple[str, str]] = frozenset(
            (a, b) for a, bs in self.succ.items() for b in bs
        )
        self.verdict: dict[str, str] = self._retrograde()
        self._draw_cache: frozenset[str] | None = None
        self._oncycle_cache: frozenset[str] | None = None

    # ------------------------------------------------------------------
    # Retrograde analysis
    # ------------------------------------------------------------------
    def _retrograde(self) -> dict[str, str]:
        """Backward propagation from the terminal (no-outgoing-edge) states.

        A state becomes WIN as soon as one successor is known LOSE; it
        becomes LOSE once every successor is known WIN.  States never
        resolved this way are DRAW.
        """
        verdict: dict[str, str] = {}
        remaining = {s: len(self.succ[s]) for s in self.states}
        queue = [s for s in self.states if remaining[s] == 0]
        for s in queue:
            verdict[s] = LOSE
        head = 0
        while head < len(queue):
            s = queue[head]
            head += 1
            for p in self.pred[s]:
                if p in verdict:
                    continue
                if verdict[s] == LOSE:
                    verdict[p] = WIN
                    queue.append(p)
                else:  # s is WIN: one more winning reply for p's opponent
                    remaining[p] -= 1
                    if remaining[p] == 0:
                        verdict[p] = LOSE
                        queue.append(p)
        for s in self.states:
            verdict.setdefault(s, DRAW)
        return verdict

    # ------------------------------------------------------------------
    # WIN / LOSE witnesses
    # ------------------------------------------------------------------
    def win_move(self, state: str) -> str:
        """Smallest-id successor that is LOSE; ``state`` must be WIN."""
        if self.verdict[state] != WIN:
            raise ValueError(f"{state!r} is not WIN")
        for t in self.succ[state]:
            if self.verdict[t] == LOSE:
                return t
        raise AssertionError("WIN state without a LOSE successor")  # unreachable

    def lose_evidence(self, state: str) -> tuple[str, ...]:
        """All successors (each of them WIN); ``state`` must be LOSE."""
        if self.verdict[state] != LOSE:
            raise ValueError(f"{state!r} is not LOSE")
        return self.succ[state]

    # ------------------------------------------------------------------
    # DRAW witnesses
    # ------------------------------------------------------------------
    @property
    def draw_states(self) -> frozenset[str]:
        if self._draw_cache is None:
            self._draw_cache = frozenset(
                s for s in self.states if self.verdict[s] == DRAW
            )
        return self._draw_cache

    @property
    def oncycle_states(self) -> frozenset[str]:
        """DRAW states that lie on a directed cycle inside the DRAW subgraph."""
        if self._oncycle_cache is None:
            draw = self.draw_states
            on: set[str] = set()
            for s in draw:
                seen: set[str] = set()
                stack = [t for t in self.succ[s] if t in draw]
                while stack:
                    x = stack.pop()
                    if x == s:
                        on.add(s)
                        break
                    if x in seen:
                        continue
                    seen.add(x)
                    stack.extend(t for t in self.succ[x] if t in draw)
            self._oncycle_cache = frozenset(on)
        return self._oncycle_cache

    def draw_witness(self, state: str) -> tuple[list[str], list[str]]:
        """Return (path, cycle) for a DRAW state, per the module docstring."""
        if self.verdict[state] != DRAW:
            raise ValueError(f"{state!r} is not DRAW")
        path = self._best_path_to_cycle(state)
        entry = path[-1]
        cycle = self._best_cycle(entry)
        # Present the cycle starting from its smallest-id state.
        i = min(range(len(cycle)), key=lambda k: cycle[k])
        cycle = cycle[i:] + cycle[:i]
        return list(path), list(cycle)

    def _best_path_to_cycle(self, start: str) -> tuple[str, ...]:
        """Best-first search for the (shortest, then id-smallest) simple path
        from ``start`` to any state lying on a DRAW-only cycle."""
        draw = self.draw_states
        oncycle = self.oncycle_states
        heap: list[tuple[int, tuple[str, ...]]] = [(0, (start,))]
        settled: set[str] = set()
        while heap:
            _, path = heapq.heappop(heap)
            u = path[-1]
            if u in settled:
                continue
            settled.add(u)
            if u in oncycle:
                return path
            for v in self.succ[u]:
                if v in draw and v not in path:
                    heapq.heappush(heap, (len(path), path + (v,)))
        raise AssertionError("DRAW state cannot reach a cycle")  # unreachable

    def _best_cycle(self, entry: str) -> tuple[str, ...]:
        """Best-first search for the (shortest, then id-smallest) simple
        directed cycle from ``entry`` back to ``entry`` in the DRAW subgraph.

        The returned tuple lists the cycle's states in order, starting at
        ``entry`` (the closing edge back to ``entry`` is implied).
        """
        draw = self.draw_states
        heap: list[tuple[int, tuple[str, ...]]] = [(0, (entry,))]
        settled: set[str] = set()
        while heap:
            depth, path = heapq.heappop(heap)
            u = path[-1]
            if depth > 0 and u == entry:
                return path[:-1]
            if u in settled:
                continue
            settled.add(u)
            for v in self.succ[u]:
                if v not in draw:
                    continue
                if v == entry or v not in path:
                    heapq.heappush(heap, (depth + 1, path + (v,)))
        raise AssertionError("on-cycle state without a cycle")  # unreachable
