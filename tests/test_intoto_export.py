"""Acceptance for `dorian export --in-toto`: a deterministic, dependency-free
in-toto Statement projection of a sealed warrant (experimental ClaimVerification
predicate). No signing, no network, no model."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, git, write
from dorian import claims_io, cli
from dorian.model import CheckerSpec, Claim, Warrant

CLAIM = Claim(
    id="h",
    text="handler() lives in app.py.",
    kind="behavior",
    load_bearing=True,
    checkers=(CheckerSpec(type="C3", program="symbol:app.py::handler"),),
)


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "app.py", "def handler():\n    return 200\n")
    write(repo, "note.md", "handler() lives in app.py.\n")
    commit_all(repo, "init")
    return repo


def _verify(repo: Path) -> int:
    claims_io.save_claims(repo / "claims.json", [CLAIM])
    return cli.main(
        ["--repo", str(repo), "verify", "note.md", "--claims", str(repo / "claims.json")]
    )


def test_export_in_toto_statement_shape(tmp_path, capsys):
    repo = _seed(tmp_path)
    assert _verify(repo) == 0
    warrant = Warrant.load(repo / "note.md.warrant")
    capsys.readouterr()  # drop the verify output

    assert cli.main(["--repo", str(repo), "export", "note.md", "--in-toto"]) == 0
    stmt = json.loads(capsys.readouterr().out)

    assert stmt["_type"] == "https://in-toto.io/Statement/v1"
    assert stmt["subject"][0]["name"] == "note.md"
    assert "sha256" in stmt["subject"][0]["digest"]
    assert stmt["predicateType"].endswith("ClaimVerification/v0.1")

    import dorian

    pred = stmt["predicate"]
    assert pred["warrantId"] == warrant.id
    assert pred["dorianVersion"] == dorian.__version__
    assert pred["bornVerifiable"] is True
    assert "h" in {c["id"] for c in pred["claims"]}
    assert "symbol:app.py::handler" in {
        ck["program"] for c in pred["claims"] for ck in c["checkers"]
    }


def test_export_in_toto_is_deterministic(tmp_path, capsys):
    repo = _seed(tmp_path)
    assert _verify(repo) == 0
    capsys.readouterr()
    assert cli.main(["--repo", str(repo), "export", "note.md", "--in-toto"]) == 0  # both calls
    out1 = capsys.readouterr().out
    assert cli.main(["--repo", str(repo), "export", "note.md", "--in-toto"]) == 0  # must succeed
    out2 = capsys.readouterr().out
    assert out1 == out2  # same warrant -> byte-identical statement


def test_export_in_toto_artifact_named_dot_warrant(tmp_path, capsys):
    """An artifact whose name literally ends in `.warrant` must export its OWN sidecar
    (`foo.warrant.warrant`), not be mis-stripped to a different/absent path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "app.py", "def handler():\n    return 200\n")
    write(repo, "foo.warrant", "handler() lives in app.py.\n")  # artifact literally named *.warrant
    commit_all(repo, "init")
    claims_io.save_claims(repo / "claims.json", [CLAIM])
    assert (
        cli.main(
            ["--repo", str(repo), "verify", "foo.warrant", "--claims", str(repo / "claims.json")]
        )
        == 0
    )
    assert (repo / "foo.warrant.warrant").is_file()  # the sidecar of the literal artifact
    capsys.readouterr()
    assert cli.main(["--repo", str(repo), "export", "foo.warrant", "--in-toto"]) == 0
    stmt = json.loads(capsys.readouterr().out)
    assert stmt["subject"][0]["name"] == "foo.warrant"


def test_export_requires_a_format(tmp_path, capsys):
    repo = _seed(tmp_path)
    assert _verify(repo) == 0
    capsys.readouterr()
    assert cli.main(["--repo", str(repo), "export", "note.md"]) != 0  # no --in-toto


def test_export_missing_warrant_is_usage_error(tmp_path):
    repo = _seed(tmp_path)
    assert cli.main(["--repo", str(repo), "export", "note.md", "--in-toto"]) != 0  # never sealed
