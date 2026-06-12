"""Seal-time scope lint + content-free (--no-quotes) sidecars.

Matrix:
scope lint ([tool.dorian.scopes] restricted globs in the TARGET repo's pyproject.toml):
(a) restricted uri blocks the seal BEFORE any checker runs: exit 6 (EXIT_SCOPE),
    no sidecar, no warrant/claim rows, one receipted scope_violation event with
    actor + matching uris/patterns under a synthetic 'unsealed:<artifact>' id
(b) --allow-restricted seals: exit 0, sidecar written, the sealed event's cause
    records the allowed_restricted uris
(c) no pyproject / no [tool.dorian.scopes] table / no restricted key -> seal
    unchanged (sealed event cause stays empty)
(d) malformed pyproject.toml -> one-line stderr + exit 2, never a traceback
(e) 'dir/**' prefix patterns match nested files at any depth
--no-quotes (content-free sidecars):
(f) sidecar bytes carry neither the planted source span nor any artifact content
    line; claim text stays; anchor line numbers retained; Warrant.load integrity ok
(g) revalidate works on a quote-less warrant: C1 re-derives the original span
    from git via the read-set entry's version ref (relocated PASS, edited FAIL),
    and status --check still reports the drift
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from conftest import AUTH_PY, CONFIG_PY, commit_all, git, write
from dorian import claims_io, cli, commands, store
from dorian.capture.manual import parse_manual
from dorian.model import Anchor, CheckerSpec, Claim, Warrant
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

SPECS = ["src/auth.py:L4-7", "src/config.py:L1-1", "src/routes.py"]

SHELL_PROGRAM = 'shell:grep -Eq "TIMEOUT *= *30" src/config.py'


def _config_claim() -> Claim:
    """A claim whose C5 shell checker FAILs once TIMEOUT drifts from 30."""
    return Claim(
        id="c1",
        text="The default request timeout is 30 seconds.",
        kind="quantity",
        load_bearing=True,
        supports=("rs-1",),
        checkers=(CheckerSpec(type="C5", program=SHELL_PROGRAM, watch=("src/config.py",)),),
    )


def _write_scopes(repo: Path, *patterns: str) -> None:
    body = ", ".join(f'"{p}"' for p in patterns)
    write(repo, "pyproject.toml", f"[tool.dorian.scopes]\nrestricted = [{body}]\n")


def _ns(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(list(argv))


def _seal_args(
    repo: Path,
    tmp_path: Path,
    *extra: str,
    specs: list[str] = SPECS,
    claims: list[Claim] | None = None,
    artifact: str = "docs/design.md",
) -> argparse.Namespace:
    rs_path, claims_path = tmp_path / "rs.json", tmp_path / "claims.json"
    parse_manual(specs, repo).dump(rs_path)
    claims_io.save_claims(claims_path, claims or [])
    argv = ["--repo", str(repo), "seal", artifact, "--readset", str(rs_path)]
    return _ns(*argv, "--claims", str(claims_path), *extra)


# --- scope lint --------------------------------------------------------------------


def test_restricted_glob_blocks_seal(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    git(fixture_repo, "config", "user.name", "dorian-test")
    _write_scopes(fixture_repo, "src/config.py")
    # drift the config so the C5 checker WOULD fail: exit 6 (not 4) proves the
    # scope lint refuses before any checker runs
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    args = _seal_args(fixture_repo, tmp_path, claims=[_config_claim()])

    assert commands.cmd_seal(args) == cli.EXIT_SCOPE == 6
    err = capsys.readouterr().err
    assert "src/config.py" in err
    assert not (fixture_repo / "docs/design.md.warrant").exists()

    conn = store.connect(fixture_repo)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM warrant").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM claim").fetchone()["c"] == 0
        events = conn.execute("SELECT * FROM event WHERE kind = 'scope_violation'").fetchall()
        assert len(events) == 1
        ev = events[0]
        assert ev["warrant_id"] == "unsealed:docs/design.md"
        assert ev["actor"] == "dorian-test"
        assert json.loads(ev["cause"]) == {
            "uris": ["src/config.py"],
            "patterns": ["src/config.py"],
        }
    finally:
        conn.close()


def test_allow_restricted_seals_and_records_allowance(fixture_repo: Path, tmp_path: Path) -> None:
    _write_scopes(fixture_repo, "src/config.py")
    args = _seal_args(fixture_repo, tmp_path, "--allow-restricted", claims=[_config_claim()])

    assert commands.cmd_seal(args) == 0
    sidecar = fixture_repo / "docs/design.md.warrant"
    assert sidecar.is_file()
    w = Warrant.load(sidecar)  # integrity-checked

    conn = store.connect(fixture_repo)
    try:
        events = conn.execute(
            "SELECT * FROM event WHERE kind = 'sealed' AND warrant_id = ?", (w.id,)
        ).fetchall()
        assert len(events) == 1
        assert json.loads(events[0]["cause"]) == {"allowed_restricted": ["src/config.py"]}
        n_violations = conn.execute(
            "SELECT COUNT(*) AS c FROM event WHERE kind = 'scope_violation'"
        ).fetchone()["c"]
        assert n_violations == 0
    finally:
        conn.close()


def test_no_scopes_config_is_unrestricted(fixture_repo: Path, tmp_path: Path) -> None:
    # no pyproject.toml at all: seal unchanged, no allowance recorded
    assert commands.cmd_seal(_seal_args(fixture_repo, tmp_path, claims=[_config_claim()])) == 0
    conn = store.connect(fixture_repo)
    try:
        events = conn.execute("SELECT cause FROM event WHERE kind = 'sealed'").fetchall()
        assert len(events) == 1
        assert events[0]["cause"] is None
    finally:
        conn.close()

    # pyproject without [tool.dorian.scopes]
    write(fixture_repo, "pyproject.toml", '[project]\nname = "x"\n')
    assert commands.cmd_seal(_seal_args(fixture_repo, tmp_path, claims=[_config_claim()])) == 0

    # [tool.dorian.scopes] table without a restricted key
    write(fixture_repo, "pyproject.toml", '[tool.dorian.scopes]\nnote = "no restricted key"\n')
    assert commands.cmd_seal(_seal_args(fixture_repo, tmp_path, claims=[_config_claim()])) == 0


def test_malformed_pyproject_is_one_line_exit_2(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    write(fixture_repo, "pyproject.toml", "not toml [[[")
    args = _seal_args(fixture_repo, tmp_path, claims=[_config_claim()])
    assert commands.cmd_seal(args) == 2
    err = capsys.readouterr().err
    assert err.startswith("dorian seal:")
    assert len(err.strip().splitlines()) == 1
    assert "Traceback" not in err
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_dir_prefix_pattern_matches_nested_files(fixture_repo: Path, tmp_path: Path) -> None:
    write(fixture_repo, "secrets/top.txt", "top secret\n")
    write(fixture_repo, "secrets/inner/key.pem", "---KEY---\n")
    commit_all(fixture_repo, "add secrets")
    _write_scopes(fixture_repo, "secrets/**")
    args = _seal_args(
        fixture_repo,
        tmp_path,
        specs=["src/auth.py:L4-7", "secrets/top.txt", "secrets/inner/key.pem"],
    )
    assert commands.cmd_seal(args) == 6
    assert not (fixture_repo / "docs/design.md.warrant").exists()

    conn = store.connect(fixture_repo)
    try:
        ev = conn.execute("SELECT * FROM event WHERE kind = 'scope_violation'").fetchone()
        assert json.loads(ev["cause"]) == {
            "uris": ["secrets/inner/key.pem", "secrets/top.txt"],
            "patterns": ["secrets/**"],
        }
    finally:
        conn.close()


# --- content-free sidecars (--no-quotes) -------------------------------------------

PLANTED = "PLANTED-SPAN-XK9Q-7741"
SECRET_SRC = f'TOKEN_HINT = "{PLANTED}"\nUNRELATED = 1\n'
NOTE_MD = "Distinctive artifact narrative line QXJ-1.\nAnother distinctive line QXJ-2.\n"


def test_no_quotes_sidecar_is_content_free(fixture_repo: Path, tmp_path: Path) -> None:
    write(fixture_repo, "src/secret_note.py", SECRET_SRC)
    write(fixture_repo, "docs/note.md", NOTE_MD)
    commit_all(fixture_repo, "plant distinctive content")
    claims = [
        Claim(
            id="c1",
            text="A token hint constant exists in the source.",
            kind="fact",
            load_bearing=False,
            anchor=Anchor(1, 1, f'TOKEN_HINT = "{PLANTED}"'),
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        )
    ]
    args = _seal_args(
        fixture_repo,
        tmp_path,
        "--no-quotes",
        specs=["src/secret_note.py:L1-1"],
        claims=claims,
        artifact="docs/note.md",
    )
    assert commands.cmd_seal(args) == 0

    sidecar = fixture_repo / "docs/note.md.warrant"
    raw = sidecar.read_bytes()
    # grep audit: no source span bytes, no artifact content line
    assert PLANTED.encode() not in raw
    assert b"TOKEN_HINT" not in raw
    for line in NOTE_MD.splitlines():
        assert line.strip()
        assert line.encode() not in raw
    # the user-authored claim text stays (it is not source content)
    assert b"A token hint constant exists in the source." in raw

    loaded = Warrant.load(sidecar)  # integrity ok over the quote-stripped body
    anchor = loaded.claims[0].anchor
    assert anchor is not None
    assert (anchor.line_start, anchor.line_end) == (1, 1)  # line numbers retained
    assert anchor.quote == ""  # quote dropped


def test_no_quotes_revalidate_round_trip(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    rs = parse_manual(["src/auth.py:L4-7"], fixture_repo)
    claims = [
        Claim(
            id="c1",
            text="Token verification uses RS256.",
            kind="fact",
            load_bearing=False,
            anchor=Anchor(3, 3, "uses RS256"),
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        )
    ]
    w = seal_artifact(fixture_repo, "docs/design.md", rs, claims, no_quotes=True)
    assert Warrant.load(fixture_repo / "docs/design.md.warrant").claims[0].anchor.quote == ""

    # span moves within the file: C1's fallback re-derives the original span from
    # git via the entry's version ref — no quote needed — and PASSes relocated
    moved = AUTH_PY.replace('"""Auth helpers."""\n', '"""Auth helpers."""\n\n# nb\n# nb\n')
    write(fixture_repo, "src/auth.py", moved)
    result = revalidate(fixture_repo, since="HEAD")
    assert [(wid, cid) for wid, cid, _ in result.relocated] == [(w.id, "c1")]
    assert not result.broken and not result.errored
    assert result.exit_code == 0

    # span edited: FAIL -> BROKEN -> DEGRADED (claim is not load-bearing)
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("RS256", "HS256"))
    result = revalidate(fixture_repo, since="HEAD")
    assert [(wid, cid) for wid, cid, _ in result.broken] == [(w.id, "c1")]
    assert result.exit_code == 3

    # status --check round trip: drift reported, DEGRADED exit
    rc = commands.cmd_status(_ns("--repo", str(fixture_repo), "status", "--check"))
    assert rc == 3
    out = capsys.readouterr().out
    assert "drifted: src/auth.py:L4-7" in out


def test_mistyped_scopes_value_is_exit_2_not_unrestricted(
    fixture_repo: Path, tmp_path: Path, capsys
) -> None:
    """[tool.dorian] scopes = "oops" must not silently degrade to unrestricted sealing."""
    write(fixture_repo, "pyproject.toml", '[tool.dorian]\nscopes = "oops"\n')
    args = _seal_args(fixture_repo, tmp_path, claims=[_config_claim()])
    assert commands.cmd_seal(args) == 2
    err = capsys.readouterr().err
    assert "must be a table" in err
    assert len(err.strip().splitlines()) == 1
    assert not (fixture_repo / "docs/design.md.warrant").exists()
