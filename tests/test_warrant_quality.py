"""`dorian bench warrant-quality` (WP8): per-claim mutation scoring.

Pins the WP8 acceptance matrix: deterministic output; a weak (existence) claim scores
its ceiling and never falsely "strong"; a strong structural claim catches its falsifying
mutation; a benign formatting mutation does not lower the score; ERROR (policy-blocked)
is its own bucket, never a miss. Offline and side-effect-free (the real repo is never
mutated)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from conftest import commit_all, git, write
from dorian.model import ProducedBy, ReadSet
from dorian.policy import ExecutionPolicy
from dorian.seal import seal_artifact

PB = ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z")


@pytest.fixture
def wq():
    """The repo-local bench module (loaded the way `dorian bench` loads it)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    return importlib.import_module("bench.warrant_quality")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/auth.py", "def verify_token(token):\n    return bool(token)\n")
    write(repo, "src/config.py", "TIMEOUT = 30\n")
    write(repo, "note.md", "# note\n\nstuff\n")
    commit_all(repo, "init")
    return repo


def _seal(repo: Path, claims: list[dict]) -> None:
    from dorian.model import CheckerSpec, Claim

    objs = [
        Claim(
            id=c["id"],
            text=c.get("text", c["id"]),
            kind=c["kind"],
            load_bearing=c.get("load_bearing", True),
            checkers=(CheckerSpec(type="C3", program=c["program"]),),
        )
        for c in claims
    ]
    seal_artifact(repo, "note.md", ReadSet(entries=(), produced_by=PB), objs)


def _score(wq, repo: Path) -> dict:
    return wq.build(repo, "note.md", ExecutionPolicy())


def test_structural_claim_catches_falsifying_mutation(wq, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _seal(
        repo,
        [{"id": "timeout", "kind": "quantity", "program": "py-const:src/config.py::TIMEOUT::30"}],
    )
    rec = _score(wq, repo)["claims"][0]
    assert rec["quality"] == "strong"
    falsify = next(m for m in rec["mutations"] if m["expectation"] == "falsify")
    assert falsify["outcome"] == "caught"  # reassigning the value -> FAIL


def test_signature_claim_catches_param_change(wq, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _seal(
        repo,
        [
            {
                "id": "sig",
                "kind": "behavior",
                "program": "py-signature:src/auth.py::verify_token::token",
            }
        ],
    )
    rec = _score(wq, repo)["claims"][0]
    falsify = next(m for m in rec["mutations"] if m["expectation"] == "falsify")
    assert falsify["outcome"] == "caught"
    benign = next(m for m in rec["mutations"] if m["expectation"] == "benign")
    assert benign["outcome"] == "ok"  # a trailing comment must not false-alarm


def test_existence_claim_shows_its_ceiling(wq, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _seal(
        repo, [{"id": "exists", "kind": "behavior", "program": "symbol:src/auth.py::verify_token"}]
    )
    rec = _score(wq, repo)["claims"][0]
    outcomes = {m["mutation"]: m["outcome"] for m in rec["mutations"]}
    assert outcomes["rename_definition"] == "caught"  # renaming the def IS caught
    assert outcomes["append_content"] == "ceiling"  # content drift keeping the name is NOT
    assert rec["strongest_strength"] == "existence"


def test_unsupported_form_is_reported_not_faked(wq, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "data.csv", "a,b\n1,2\n")
    commit_all(repo, "data")
    _seal(repo, [{"id": "rows", "kind": "quantity", "program": "string:src/config.py::TIMEOUT"}])
    rec = _score(wq, repo)["claims"][0]
    # string: is not deterministically mutated by the harness -> reported, never faked
    assert any(m["outcome"] == "unsupported" for m in rec["mutations"])


def test_deterministic_output(wq, tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _seal(
        repo,
        [{"id": "timeout", "kind": "quantity", "program": "py-const:src/config.py::TIMEOUT::30"}],
    )
    assert _score(wq, repo) == _score(wq, repo)
    # and the real repo file was never mutated
    assert (repo / "src/config.py").read_text() == "TIMEOUT = 30\n"


def test_cli_smoke_json(wq, tmp_path: Path, capsys) -> None:
    from dorian import cli

    repo = _repo(tmp_path)
    _seal(
        repo,
        [{"id": "timeout", "kind": "quantity", "program": "py-const:src/config.py::TIMEOUT::30"}],
    )
    # --repo after the bench subcommand: it flows to the bench module's own parser
    rc = cli.main(["bench", "warrant-quality", "note.md", "--repo", str(repo), "--json"])
    assert rc == 0
    import json

    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "dorian-warrant-quality-v1"
    assert out["summary"]["by_quality"].get("strong") == 1
