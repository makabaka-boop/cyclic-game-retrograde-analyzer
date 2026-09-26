"""End-to-end CLI behaviour: JSON in, JSON out, exit codes."""

from __future__ import annotations

import io
import json

from gamegraph.cli import EXIT_INPUT_ERROR, EXIT_OK, main

SAMPLE = {
    "states": ["a", "b", "c", "d"],
    "edges": [
        {"from": "a", "to": "b"},
        {"from": "b", "to": "a"},
        {"from": "b", "to": "c"},
        {"from": "c", "to": "d"},
    ],
    "queries": ["a", "c", "d"],
}

EXPECTED_REPORT = {
    "verdicts": {
        "a": {"verdict": "DRAW"},
        "b": {"verdict": "DRAW"},
        "c": {"verdict": "WIN", "move": {"from": "c", "to": "d"}},
        "d": {"verdict": "LOSE", "evidence": []},
    },
    "queries": [
        {
            "state": "a",
            "verdict": "DRAW",
            "witness": {"path": ["a"], "cycle": ["a", "b"]},
        },
        {"state": "c", "verdict": "WIN", "move": {"from": "c", "to": "d"}},
        {"state": "d", "verdict": "LOSE", "evidence": []},
    ],
}


def run_cli(argv, stdin_text=""):
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv, stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_stdin_roundtrip():
    code, out, err = run_cli([], json.dumps(SAMPLE))
    assert code == EXIT_OK
    assert err == ""
    assert json.loads(out) == EXPECTED_REPORT


def test_file_input_and_compact(tmp_path):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    code, out, err = run_cli([str(path), "--compact"])
    assert code == EXIT_OK
    assert err == ""
    assert "\n" == out[-1] and out.count("\n") == 1
    assert json.loads(out) == EXPECTED_REPORT


def test_missing_file_is_rejected():
    code, out, err = run_cli(["/nonexistent/input.json"])
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "cannot read input" in json.loads(err)["error"]


def test_invalid_json_is_rejected():
    code, out, err = run_cli([], "{not json")
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "invalid JSON" in json.loads(err)["error"]


def test_duplicate_edge_rejects_whole_input():
    doc = {
        "states": ["a", "b"],
        "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}],
    }
    code, out, err = run_cli([], json.dumps(doc))
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "duplicate edge" in json.loads(err)["error"]


def test_unknown_state_rejects_whole_input():
    doc = {"states": ["a", "b"], "edges": [{"from": "a", "to": "zzz"}]}
    code, out, err = run_cli([], json.dumps(doc))
    assert code == EXIT_INPUT_ERROR
    assert out == ""
    assert "unknown state" in json.loads(err)["error"]


def test_lose_evidence_lists_all_successors():
    doc = {
        "states": ["x", "w1", "w2", "t"],
        "edges": [
            {"from": "x", "to": "w1"},
            {"from": "x", "to": "w2"},
            {"from": "w1", "to": "t"},
            {"from": "w2", "to": "t"},
        ],
        "queries": ["x"],
    }
    code, out, _ = run_cli([], json.dumps(doc))
    assert code == EXIT_OK
    report = json.loads(out)
    evidence = report["verdicts"]["x"]["evidence"]
    assert evidence == [
        {"from": "x", "to": "w1", "verdict": "WIN"},
        {"from": "x", "to": "w2", "verdict": "WIN"},
    ]
    assert report["queries"][0]["evidence"] == evidence
