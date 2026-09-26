"""JSON command-line interface for the game graph analyzer.

Usage::

    python -m gamegraph.cli [--pretty] [request.json]

The request is read from the given file or standard input; the analysis is
written to standard output.  Rejected requests exit with status ``2`` and a
JSON error document on standard error::

    {"status": "error", "errors": ["..."]}
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .analyzer import ValidationError, analyze


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gamegraph",
        description="Classify states of a finite cyclic game as WIN/LOSE/DRAW.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="JSON request file (default: read standard input)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print the JSON response",
    )
    args = parser.parse_args(argv)

    try:
        if args.file:
            with open(args.file, "r", encoding="ascii") as fh:
                payload = json.load(fh)
        else:
            payload = json.load(sys.stdin)
    except FileNotFoundError:
        payload_error = [f"cannot open input file: {args.file}"]
        json.dump({"status": "error", "errors": payload_error}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    except json.JSONDecodeError as exc:
        json.dump(
            {"status": "error", "errors": [f"invalid JSON: {exc.msg} at line "
                                           f"{exc.lineno} column {exc.colno}"]},
            sys.stderr,
        )
        sys.stderr.write("\n")
        return 2
    except UnicodeDecodeError:
        json.dump(
            {"status": "error", "errors": ["input is not ASCII/UTF-8 encoded"]},
            sys.stderr,
        )
        sys.stderr.write("\n")
        return 2

    try:
        result = analyze(payload)
    except ValidationError as exc:
        json.dump({"status": "error", "errors": exc.errors}, sys.stderr, indent=2)
        sys.stderr.write("\n")
        return 2

    indent = 2 if args.pretty else None
    json.dump(result, sys.stdout, indent=indent, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
