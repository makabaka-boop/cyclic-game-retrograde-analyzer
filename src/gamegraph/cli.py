"""Command-line interface: read a JSON game graph, emit a JSON report.

Usage:
    gamegraph [input.json] [--compact]

With no argument the document is read from stdin.  The report is written to
stdout; any validation problem rejects the whole input with a JSON error on
stderr and exit status 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from . import __version__
from .model import GameInput, InputError, parse_input
from .solver import DRAW, LOSE, WIN, GameGraph

EXIT_OK = 0
EXIT_INPUT_ERROR = 2


def build_report(game: GameGraph, queries: tuple[str, ...]) -> dict:
    """Assemble the JSON report: verdicts for all states, witnesses for queries."""

    def move_item(s: str) -> dict:
        return {"from": s, "to": game.win_move(s)}

    def evidence_items(s: str) -> list[dict]:
        return [
            {"from": s, "to": t, "verdict": game.verdict[t]}
            for t in game.lose_evidence(s)
        ]

    verdicts: dict[str, dict] = {}
    for s in game.states:
        v = game.verdict[s]
        item: dict = {"verdict": v}
        if v == WIN:
            item["move"] = move_item(s)
        elif v == LOSE:
            item["evidence"] = evidence_items(s)
        verdicts[s] = item

    query_items: list[dict] = []
    for q in queries:
        v = game.verdict[q]
        item = {"state": q, "verdict": v}
        if v == WIN:
            item["move"] = move_item(q)
        elif v == LOSE:
            item["evidence"] = evidence_items(q)
        else:
            path, cycle = game.draw_witness(q)
            item["witness"] = {"path": path, "cycle": cycle}
        query_items.append(item)

    return {"verdicts": verdicts, "queries": query_items}


def _fail(stderr: TextIO, message: str) -> int:
    json.dump({"error": message}, stderr, ensure_ascii=True)
    stderr.write("\n")
    return EXIT_INPUT_ERROR


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    parser = argparse.ArgumentParser(
        prog="gamegraph",
        description="Retrograde WIN/LOSE/DRAW analysis of a finite directed "
        "game graph given as JSON.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="JSON input file (default: read from stdin)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit the report as a single line",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args(argv)

    try:
        if args.input is None:
            text = stdin.read()
        else:
            text = Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        return _fail(stderr, f"cannot read input: {exc}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return _fail(stderr, f"invalid JSON: {exc}")

    try:
        spec: GameInput = parse_input(data)
    except InputError as exc:
        return _fail(stderr, str(exc))

    game = GameGraph(spec.states, spec.edges)
    report = build_report(game, spec.queries)
    json.dump(
        report,
        stdout,
        ensure_ascii=True,
        sort_keys=True,
        indent=None if args.compact else 2,
    )
    stdout.write("\n")
    return EXIT_OK


def run() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
