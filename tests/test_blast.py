"""Blast-radius tests: downstream traversal over the derives index.

Matrix:
(a) chain A <- B <- C (B's read-set includes A's artifact, C's includes B's):
    blast from A's source path lists B at depth 1 and C at depth 2, with `via`
    naming the upstream warrant that linked each in
(b) warrant-id seed (sha256:...) gives the same result as the path seed
(c) max_depth bounds the traversal
(d) a hand-inserted derives row closing a loop terminates with each warrant
    visited once (seed cycle and non-seed cycle)
(e) unknown path / unknown warrant id -> empty list
(f) cmd_blast: text one-line-per-hit, --json payload, 'no downstream warrants'
    on empty (exit 0), --max-depth flag, missing --repo is usage (exit 2),
    target outside the repo is usage (exit 2)
(g) sync-rebuild invariant: delete the DB, `dorian sync`, blast output is
    identical (derives edges are reconstructible from sidecars)
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import AUTH_PY, commit_all, write
from dorian import cli, commands, store
from dorian.blast import blast
from dorian.capture.manual import parse_manual
from dorian.model import CheckerSpec, Claim
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact


def _seal_chain(repo: Path):
    """Three artifacts A <- B <- C: B reads A's artifact, C reads B's, so
    seal-time derives_from inference links B -> A and C -> B."""
    w_a = seal_artifact(repo, "docs/design.md", parse_manual(["src/auth.py"], repo), [])
    write(repo, "docs/b.md", "# B\n\nBuilds on docs/design.md.\n")
    w_b = seal_artifact(repo, "docs/b.md", parse_manual(["docs/design.md"], repo), [])
    write(repo, "docs/c.md", "# C\n\nBuilds on docs/b.md.\n")
    w_c = seal_artifact(repo, "docs/c.md", parse_manual(["docs/b.md"], repo), [])
    commit_all(repo, "seal chain A <- B <- C")
    return w_a, w_b, w_c


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


# --- (a) chain via path seed -------------------------------------------------------


def test_chain_path_seed(fixture_repo: Path) -> None:
    w_a, w_b, w_c = _seal_chain(fixture_repo)
    hits = blast(fixture_repo, "src/auth.py")
    assert [(h["warrant_id"], h["depth"], h["via"]) for h in hits] == [
        (w_b.id, 1, w_a.id),
        (w_c.id, 2, w_b.id),
    ]
    assert [h["artifact_uri"] for h in hits] == ["docs/b.md", "docs/c.md"]
    assert all(h["trust_state"] == "WARRANTED" for h in hits)


# --- (b) warrant-id seed -----------------------------------------------------------


def test_warrant_id_seed_matches_path_seed(fixture_repo: Path) -> None:
    w_a, _, _ = _seal_chain(fixture_repo)
    assert blast(fixture_repo, w_a.id) == blast(fixture_repo, "src/auth.py")


# --- (c) max_depth bound -----------------------------------------------------------


def test_max_depth_bound(fixture_repo: Path) -> None:
    w_a, w_b, _ = _seal_chain(fixture_repo)
    hits = blast(fixture_repo, w_a.id, max_depth=1)
    assert [(h["warrant_id"], h["depth"]) for h in hits] == [(w_b.id, 1)]
    assert blast(fixture_repo, w_a.id, max_depth=0) == []


# --- (d) cycles terminate, each warrant once ----------------------------------------


def _close_loop(repo: Path, from_warrant: str, to_warrant: str) -> None:
    """Hand-insert a derives row (downstream, upstream) closing a loop."""
    conn = store.connect(repo)
    try:
        conn.execute(
            "INSERT INTO derives (from_warrant, to_warrant, via) VALUES (?, ?, NULL)",
            (from_warrant, to_warrant),
        )
        conn.commit()
    finally:
        conn.close()


def test_cycle_back_to_seed_terminates(fixture_repo: Path) -> None:
    w_a, w_b, w_c = _seal_chain(fixture_repo)
    _close_loop(fixture_repo, w_a.id, w_c.id)  # A derives from C: C's downstream is A
    hits = blast(fixture_repo, w_a.id)
    assert [(h["warrant_id"], h["depth"]) for h in hits] == [(w_b.id, 1), (w_c.id, 2)]


def test_cycle_through_non_seed_terminates(fixture_repo: Path) -> None:
    """Seeded at B with the loop A -> C in place, the walk reaches A at depth 2
    and must not re-enter B (each warrant visited once)."""
    w_a, w_b, w_c = _seal_chain(fixture_repo)
    _close_loop(fixture_repo, w_a.id, w_c.id)
    hits = blast(fixture_repo, w_b.id)
    assert [(h["warrant_id"], h["depth"], h["via"]) for h in hits] == [
        (w_c.id, 1, w_b.id),
        (w_a.id, 2, w_c.id),
    ]


# --- (e) unknown targets ------------------------------------------------------------


def test_unknown_targets_empty(fixture_repo: Path) -> None:
    _seal_chain(fixture_repo)
    assert blast(fixture_repo, "src/never-read.py") == []
    assert blast(fixture_repo, "sha256:" + "0" * 64) == []


# --- (f) cmd_blast -----------------------------------------------------------------


def test_cmd_blast_text(fixture_repo: Path, capsys) -> None:
    w_a, w_b, _ = _seal_chain(fixture_repo)
    assert commands.cmd_blast(_ns("--repo", str(fixture_repo), "blast", "src/auth.py")) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "docs/b.md" in lines[0] and "depth=1" in lines[0]
    assert "WARRANTED" in lines[0] and w_a.id[:23] in lines[0]
    assert "docs/c.md" in lines[1] and "depth=2" in lines[1] and w_b.id[:23] in lines[1]


def test_cmd_blast_json(fixture_repo: Path, capsys) -> None:
    w_a, w_b, w_c = _seal_chain(fixture_repo)
    assert commands.cmd_blast(_ns("--json", "--repo", str(fixture_repo), "blast", w_a.id)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"] == w_a.id
    assert [h["warrant_id"] for h in data["hits"]] == [w_b.id, w_c.id]
    assert [h["depth"] for h in data["hits"]] == [1, 2]


def test_cmd_blast_max_depth_flag(fixture_repo: Path, capsys) -> None:
    w_a, _, _ = _seal_chain(fixture_repo)
    args = _ns("--repo", str(fixture_repo), "blast", w_a.id, "--max-depth", "1")
    assert commands.cmd_blast(args) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and "docs/b.md" in lines[0]


def test_cmd_blast_empty_is_ok(fixture_repo: Path, capsys) -> None:
    _, _, w_c = _seal_chain(fixture_repo)
    assert commands.cmd_blast(_ns("--repo", str(fixture_repo), "blast", w_c.id)) == 0
    assert capsys.readouterr().out.strip() == "no downstream warrants"
    assert commands.cmd_blast(_ns("--repo", str(fixture_repo), "blast", "src/nope.py")) == 0
    assert capsys.readouterr().out.strip() == "no downstream warrants"


def test_cmd_blast_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    args = _ns("--repo", str(tmp_path / "nope"), "blast", "src/auth.py")
    assert commands.cmd_blast(args) == 2
    err = capsys.readouterr().err
    assert "dorian blast:" in err
    assert "corrupt warrant sidecar" not in err


def test_cmd_blast_target_outside_repo_is_usage(fixture_repo: Path, capsys) -> None:
    args = _ns("--repo", str(fixture_repo), "blast", "/etc/hosts")
    assert commands.cmd_blast(args) == 2
    err = capsys.readouterr().err
    assert "dorian blast:" in err and "outside repo" in err


# --- supersede lineage: re-sealed upstream stays blast/recall-reachable --------------


def _sync(repo: Path) -> None:
    conn = store.connect(repo)
    try:
        store.sync(repo, conn)
    finally:
        conn.close()


def test_blast_follows_supersede_after_upstream_reseal(fixture_repo: Path) -> None:
    """Regression: a --supersede re-seal replaced the upstream sidecar, the
    downstream derives_from kept the dead predecessor id, sync dropped the dead
    warrant row, and blast went permanently blind for the whole downstream
    graph. The walk now expands each frontier warrant with the ids it
    supersedes, reporting hits via the live successor."""
    w_a, w_b, w_c = _seal_chain(fixture_repo)

    # routine doc maintenance: fix the doc, re-seal, explicitly superseding
    write(fixture_repo, "docs/design.md", "# Design v2\n\nStill reads src/auth.py.\n")
    w_a2 = seal_artifact(
        fixture_repo,
        "docs/design.md",
        parse_manual(["src/auth.py"], fixture_repo),
        [],
        supersede=w_a.id,
    )
    commit_all(fixture_repo, "doc fix + re-seal")
    assert w_a2.id != w_a.id and w_a2.supersedes == w_a.id
    _sync(fixture_repo)  # drops the dead predecessor row, as any command would

    hits = blast(fixture_repo, "src/auth.py")
    assert [(h["warrant_id"], h["depth"], h["via"]) for h in hits] == [
        (w_b.id, 1, w_a2.id),  # via the LIVE successor, not the dead id
        (w_c.id, 2, w_b.id),
    ]
    assert blast(fixture_repo, w_a2.id) == hits  # new-id seed agrees with the path seed


def test_recall_survives_upstream_reseal(fixture_repo: Path) -> None:
    """Regression: after a --supersede re-seal, breaking the upstream source
    again revoked the new upstream with NO 'recalled' flag for the
    still-derived downstream (revalidate's recall pass goes through blast)."""
    claim = Claim(
        id="c1",
        text="Token verification uses RS256.",
        kind="fact",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="string:src/auth.py::RS256"),),
    )
    w_a = seal_artifact(
        fixture_repo, "docs/design.md", parse_manual(["src/auth.py"], fixture_repo), [claim]
    )
    write(fixture_repo, "docs/b.md", "# B\n\nBuilds on docs/design.md.\n")
    w_b = seal_artifact(
        fixture_repo, "docs/b.md", parse_manual(["docs/design.md"], fixture_repo), []
    )
    commit_all(fixture_repo, "seal A and B")

    write(fixture_repo, "docs/design.md", "# Design v2\n\nStill RS256-based.\n")
    w_a2 = seal_artifact(
        fixture_repo,
        "docs/design.md",
        parse_manual(["src/auth.py"], fixture_repo),
        [claim],
        supersede=w_a.id,
    )
    base = commit_all(fixture_repo, "doc fix + re-seal")

    write(fixture_repo, "src/auth.py", AUTH_PY.replace("RS256", "ES256"))
    commit_all(fixture_repo, "rotate signing algorithm")

    res = revalidate(fixture_repo, since=base)
    assert [(wid, cid) for wid, cid, _ in res.broken] == [(w_a2.id, "c1")]
    assert [(e["warrant_id"], e["via"]) for e in res.recalled] == [(w_b.id, w_a2.id)]


# --- (g) sync-rebuild invariant -----------------------------------------------------


def test_blast_identical_after_db_rebuild(fixture_repo: Path, capsys) -> None:
    """Sidecars are the source of truth: deleting the index and rebuilding it
    with `dorian sync` must reproduce the exact same blast output."""
    _seal_chain(fixture_repo)
    before = blast(fixture_repo, "src/auth.py")
    assert before  # guard: the invariant is vacuous on an empty result

    db = store.db_path(fixture_repo)
    for p in db.parent.glob(db.name + "*"):  # index.sqlite + -wal/-shm
        p.unlink()
    assert commands.cmd_sync(_ns("--repo", str(fixture_repo), "sync")) == 0
    capsys.readouterr()

    assert blast(fixture_repo, "src/auth.py") == before
