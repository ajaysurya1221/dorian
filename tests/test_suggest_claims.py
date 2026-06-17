"""Acceptance for `dorian suggest-claims`: a deterministic, zero-model C3 claim
suggester whose output seals unmodified (born-verifiable scaffolding)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, git, write
from dorian import cli

APP = '''\
TIMEOUT = 30
NAME = "svc"
PORTS = [80, 443]


def handler():
    return 200


class Service:
    pass


_PRIVATE = 1


def _helper():
    return None
'''


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "app.py", APP)
    commit_all(repo, "init")
    return repo


def _suggest(repo: Path, capsys) -> dict:
    capsys.readouterr()
    assert cli.main(["--repo", str(repo), "suggest-claims", "app.py"]) == 0
    return json.loads(capsys.readouterr().out)


def test_suggest_claims_proposes_symbol_and_const_claims(tmp_path, capsys):
    frag = _suggest(_seed(tmp_path), capsys)
    progs = {ck["program"] for c in frag["claims"] for ck in c["checkers"]}
    assert "symbol:app.py::handler" in progs
    assert "symbol:app.py::Service" in progs
    assert "py-const:app.py::TIMEOUT::30" in progs
    assert "py-const:app.py::NAME::'svc'" in progs


def test_suggest_claims_is_conservative(tmp_path, capsys):
    frag = _suggest(_seed(tmp_path), capsys)
    progs = {ck["program"] for c in frag["claims"] for ck in c["checkers"]}
    # private defs/constants are skipped
    assert not any("_helper" in p or "_PRIVATE" in p for p in progs)
    # containers are NOT proposed as py-const (conservative)
    assert not any("PORTS" in p for p in progs)
    # every suggestion is non-load-bearing by default
    assert all(c["load_bearing"] is False for c in frag["claims"])


def test_suggest_claims_output_seals_unmodified(tmp_path, capsys):
    """The whole point: the suggested fragment is born-verifiable — feeding it
    straight to `dorian verify` seals (exit 0)."""
    repo = _seed(tmp_path)
    frag = _suggest(repo, capsys)
    (repo / "claims.json").write_text(json.dumps({"claims": frag["claims"]}))
    capsys.readouterr()
    claims_path = str(repo / "claims.json")
    assert cli.main(["--repo", str(repo), "verify", "app.py", "--claims", claims_path]) == 0


def test_suggest_claims_is_deterministic(tmp_path, capsys):
    repo = _seed(tmp_path)
    a = _suggest(repo, capsys)
    b = _suggest(repo, capsys)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_suggest_claims_rejects_non_python(tmp_path):
    repo = _seed(tmp_path)
    write(repo, "data.txt", "hello\n")
    commit_all(repo, "txt")
    assert cli.main(["--repo", str(repo), "suggest-claims", "data.txt"]) != 0
