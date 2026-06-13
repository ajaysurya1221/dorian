"""`dorian verify`: one-shot auto-capture + seal for the agent-claims workflow.

verify derives the read-set from the files the claims' C3/C4/C5 checkers name,
then seals. Because seal is born-verifiable, a zero exit proves every backed
claim held against the current sources; a false claim refuses the seal (exit 4)
and writes no sidecar. C1 span claims bind a read-set entry, not a file, so they
are rejected (exit 2) with a pointer to explicit capture + seal.
"""

from __future__ import annotations

from pathlib import Path

from dorian import claims_io, cli, store
from dorian.model import CheckerSpec, Claim


def _claim(cid: str, text: str, spec: CheckerSpec, *, kind: str = "reference") -> Claim:
    return Claim(id=cid, text=text, kind=kind, load_bearing=False, supports=(), checkers=(spec,))


def _write_claims(repo: Path, claims: list[Claim]) -> Path:
    path = repo / "claims.json"
    claims_io.save_claims(path, claims)
    return path


def test_verify_auto_captures_then_seals(fixture_repo: Path, capsys) -> None:
    claims = [
        _claim(
            "a1",
            "Login is served at /v1/login.",
            CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),
        ),
        _claim(
            "a2",
            "The lots dataset has 4 rows.",
            CheckerSpec(type="C5", program="rowcount:data/lots.csv::== 4"),
            kind="quantity",
        ),
    ]
    path = _write_claims(fixture_repo, claims)

    rc = cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(path)])

    assert rc == 0
    assert (fixture_repo / "docs/design.md.warrant").is_file()
    assert "verified 2/2 claim(s)" in capsys.readouterr().out
    # the read-set was auto-derived from exactly the files the claims reference
    conn = store.connect(fixture_repo)
    try:
        uris = {r["uri"] for r in conn.execute("SELECT uri FROM resource WHERE scope = 'project'")}
    finally:
        conn.close()
    assert uris == {"src/routes.py", "data/lots.csv"}


def test_verify_refuses_a_false_claim_and_writes_nothing(fixture_repo: Path, capsys) -> None:
    claims = [
        _claim(
            "a1",
            "Login is served at /v2/login.",
            CheckerSpec(type="C3", program="string:src/routes.py::/v2/login"),
        ),
    ]
    path = _write_claims(fixture_repo, claims)

    rc = cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(path)])

    assert rc == 4  # EXIT_REVOKED: born-verifiable seal refuses a claim false right now
    assert not (fixture_repo / "docs/design.md.warrant").exists()
    assert "dorian verify:" in capsys.readouterr().err


def test_verify_rejects_c1_span_claims(fixture_repo: Path, capsys) -> None:
    claims = [
        Claim(
            id="a1",
            text="uses RS256",
            kind="fact",
            load_bearing=False,
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        ),
    ]
    path = _write_claims(fixture_repo, claims)

    rc = cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(path)])

    assert rc == 2  # EXIT_USAGE: C1 needs explicit capture + seal
    assert not (fixture_repo / "docs/design.md.warrant").exists()
    assert "C1 span claims" in capsys.readouterr().err
