"""Revalidation unit tests.

Matrix:
(a) unrelated change -> zero candidates, exit 0, no claim/fold events, no folds
(b) rename-only change -> only the C1 claim is a candidate, re-checked, passes
    as relocated, claim stays VERIFIED, fold lands TRUSTED, exit 0
(c) render_text / render_json sanity (json round-trips via json.loads)
(d) cmd_revalidate: neither --since nor --changed-paths is usage (exit 2), as
    are both together, an unreadable/missing --changed-paths file, and a
    nonexistent --repo (never labeled an integrity failure); the listing is
    read exactly once (no validate-then-reread race); a working-tree TIMEOUT
    drift since HEAD breaks the load-bearing claim (json output, exit 4);
    cmd_report prints stale/broken events and the current trust state; a bad
    or overflowing --since spec for report and a nonexistent --repo are usage
    (exit 2)
(e) perf smoke: 200 synthesized sidecar warrants x 5 claims; sync + revalidate
    touching 3 files completes < 5s wall and re-checks exactly 15 claims
(f) errored pathway: a checker that cannot run (unregistered type) yields
    claim ERRORED — never BROKEN — folding to UNKNOWN, exit 5
(g) only a non-load-bearing claim breaks -> default policy folds DEGRADED,
    exit 3 (the revoke/degrade distinction through revalidate)
(h) an unbacked candidate claim is marked stale but never re-stated: state
    stays UNBACKED, no fabricated VERIFIED/BROKEN, exit 0
(i) recall flags: a NEWLY broken claim in A emits 'recalled' events for every
    downstream warrant (B, C) — events only: downstream claim/trust states are
    untouched, exit semantics unchanged, and an already-BROKEN claim on a
    second run recalls nothing
(j) regex auto-watch regression: a watch-less C3 regex: checker derives
    watch=(<file>,) at seal time — not the junk '<file>::<pattern>' path — so
    revalidate still selects and breaks the claim when the file changes
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import CONFIG_PY, ROUTES_PY, apply_unrelated_commit, commit_all, git, write
from dorian import claims_io, cli, commands, gitio, store
from dorian.capture.manual import parse_manual
from dorian.model import (
    Anchor,
    CheckerSpec,
    Claim,
    FoldPolicy,
    ProducedBy,
    ReadSetEntry,
    Warrant,
    sha256_hex,
)
from dorian.report import report_since
from dorian.revalidate import RevalResult, render_json, render_text, revalidate
from dorian.seal import seal_artifact

SPECS = ["src/auth.py:L4-7", "src/config.py:L1-1", "src/routes.py", "data/lots.csv"]

SHELL_PROGRAM = 'shell:grep -Eq "TIMEOUT *= *30" src/config.py'


def make_claims() -> list[Claim]:
    """The 4 demo claims over the fixture read-set (same set as the seal task)."""
    return [
        Claim(
            id="c1",
            text="Token verification lives in src/auth.py and uses RS256.",
            kind="fact",
            load_bearing=True,
            anchor=Anchor(3, 3, "uses RS256"),
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        ),
        Claim(
            id="c2",
            text="The default request timeout is 30 seconds.",
            kind="quantity",
            load_bearing=True,
            supports=("rs-1",),
            checkers=(CheckerSpec(type="C5", program=SHELL_PROGRAM, watch=("src/config.py",)),),
        ),
        Claim(
            id="c3",
            text="Login is served at /v1/login.",
            kind="reference",
            load_bearing=False,
            supports=("rs-2",),
            checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
        ),
        Claim(
            id="c4",
            text="The lots dataset has 4 rows.",
            kind="quantity",
            load_bearing=False,
            supports=("rs-3",),
            checkers=(CheckerSpec(type="C5", program="rowcount:data/lots.csv::== 4"),),
        ),
    ]


def _sealed(repo: Path) -> Warrant:
    return seal_artifact(repo, "docs/design.md", parse_manual(SPECS, repo), make_claims())


def _audit_kinds(repo: Path) -> list[str]:
    conn = store.connect(repo)
    try:
        return [r["kind"] for r in conn.execute("SELECT kind FROM event ORDER BY seq")]
    finally:
        conn.close()


# --- (a) unrelated change --------------------------------------------------------


def test_unrelated_change_zero_candidates(fixture_repo: Path) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    apply_unrelated_commit(fixture_repo)

    res = revalidate(fixture_repo, since=base)
    assert res.candidates == 0
    assert res.exit_code == 0
    assert res.broken == res.relocated == res.errored == res.passed == []
    assert res.folds == {}
    # no claim/fold events: the only event is the seal-time 'sealed'
    assert [k for k in _audit_kinds(fixture_repo) if k.startswith(("claim.", "fold."))] == []


# --- (b) rename-only change ------------------------------------------------------


def test_rename_only_relocated_pass(fixture_repo: Path) -> None:
    w = _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    git(fixture_repo, "mv", "src/auth.py", "src/tokens.py")
    commit_all(fixture_repo, "rename auth module")

    res = revalidate(fixture_repo, since=base)
    assert res.candidates == 1  # only the C1 claim watches src/auth.py
    assert [(wid, cid) for wid, cid, _ in res.relocated] == [(w.id, "c1")]
    assert all(detail for _, _, detail in res.relocated)
    assert res.broken == res.errored == res.passed == []
    assert res.folds == {w.id: ("WARRANTED", "TRUSTED")}
    assert res.exit_code == 0

    conn = store.connect(fixture_repo)
    try:
        states = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w.id)}
        trust = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()[
            "trust_state"
        ]
    finally:
        conn.close()
    assert states["c1"] == "VERIFIED"
    assert trust == "TRUSTED"


# --- (b2) rename log: post-rename binding blindness --------------------------------


def test_rename_then_edit_breaks(fixture_repo: Path) -> None:
    """The silent false-TRUSTED probe: seal; rename src/auth.py -> src/tokens.py
    (C1 relocates, PASS); then edit the claimed fact inside src/tokens.py
    (RS256 -> HS256) and revalidate --since the rename sha. The binding stored
    under the OLD path must still surface as a candidate via the persisted
    rename log, C1 must FAIL, and the fold must REVOKE (exit 4)."""
    w = _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    git(fixture_repo, "mv", "src/auth.py", "src/tokens.py")
    rename_sha = commit_all(fixture_repo, "rename auth module")
    res1 = revalidate(fixture_repo, since=base)
    assert [(wid, cid) for wid, cid, _ in res1.relocated] == [(w.id, "c1")]

    tokens = fixture_repo / "src" / "tokens.py"
    write(fixture_repo, "src/tokens.py", tokens.read_text().replace("RS256", "HS256"))
    commit_all(fixture_repo, "switch token signing to HS256")

    res2 = revalidate(fixture_repo, since=rename_sha)
    assert res2.candidates == 1  # found via the rename log, not the exact path
    assert [(wid, cid) for wid, cid, _ in res2.broken] == [(w.id, "c1")]
    assert res2.folds == {w.id: ("TRUSTED", "REVOKED")}
    assert res2.exit_code == 4


def test_rename_chain_then_edit_breaks(fixture_repo: Path) -> None:
    """a -> b then b -> c across separate revalidations: the persisted rename
    log must resolve the chain so a claim bound to the original path follows
    the file across both renames and still breaks on a fact edit."""
    w = _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    git(fixture_repo, "mv", "src/auth.py", "src/tokens.py")
    sha_ab = commit_all(fixture_repo, "rename auth -> tokens")
    revalidate(fixture_repo, since=base)
    git(fixture_repo, "mv", "src/tokens.py", "src/jwt.py")
    sha_bc = commit_all(fixture_repo, "rename tokens -> jwt")
    res1 = revalidate(fixture_repo, since=sha_ab)
    assert [(wid, cid) for wid, cid, _ in res1.relocated] == [(w.id, "c1")]
    assert res1.exit_code == 0

    jwt = fixture_repo / "src" / "jwt.py"
    write(fixture_repo, "src/jwt.py", jwt.read_text().replace("RS256", "HS256"))
    commit_all(fixture_repo, "switch token signing to HS256")

    res2 = revalidate(fixture_repo, since=sha_bc)
    assert res2.candidates == 1
    assert [(wid, cid) for wid, cid, _ in res2.broken] == [(w.id, "c1")]
    assert res2.exit_code == 4


# --- (c) rendering ---------------------------------------------------------------


def test_render_text_and_json() -> None:
    res = RevalResult(
        broken=[("sha256:w", "c2", "exit code 1")],
        relocated=[("sha256:w", "c1", "relocated")],
        errored=[],
        passed=[],
        folds={"sha256:w": ("TRUSTED", "REVOKED")},
        candidates=2,
        exit_code=4,
    )
    text = render_text(res)
    assert "2 candidate" in text
    assert "BROKEN" in text and "c2" in text
    assert "RELOCATED" in text and "c1" in text
    assert "TRUSTED -> REVOKED" in text

    data = json.loads(render_json(res))
    assert data["candidates"] == 2
    assert data["exit_code"] == 4
    assert data["broken"] == [["sha256:w", "c2", "exit code 1"]]
    assert data["folds"] == {"sha256:w": ["TRUSTED", "REVOKED"]}


# --- (d) command handlers --------------------------------------------------------


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def test_cmd_revalidate_requires_since_or_changed_paths(fixture_repo: Path, capsys) -> None:
    assert commands.cmd_revalidate(_ns("--repo", str(fixture_repo), "revalidate")) == 2
    assert "dorian revalidate:" in capsys.readouterr().err


def test_cmd_revalidate_json_then_report(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    # uncommitted working-tree drift must be seen (diff against since directly)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))

    args = _ns("--repo", str(fixture_repo), "revalidate", "--since", base, "--format", "json")
    rc = commands.cmd_revalidate(args)
    data = json.loads(capsys.readouterr().out)
    assert rc == 4  # load-bearing claim broke -> fold REVOKED
    assert data["candidates"] == 1
    assert [c for _, c, _ in data["broken"]] == ["c2"]

    assert commands.cmd_report(_ns("--repo", str(fixture_repo), "report", "--since", "7d")) == 0
    out = capsys.readouterr().out
    assert "claim.stale" in out
    assert "claim.broken" in out
    assert "REVOKED" in out
    assert "docs/design.md" in out


def test_report_rejects_bad_since_spec(fixture_repo: Path, capsys) -> None:
    with pytest.raises(ValueError, match="since"):
        report_since(fixture_repo, "soon")
    assert commands.cmd_report(_ns("--repo", str(fixture_repo), "report", "--since", "soon")) == 2
    assert "dorian report:" in capsys.readouterr().err


def test_report_rejects_overflowing_since_spec(fixture_repo: Path, capsys) -> None:
    # syntactically valid specs whose window overflows timedelta / datetime
    for spec in ("999999999999d", "999999d"):
        with pytest.raises(ValueError, match="since"):
            report_since(fixture_repo, spec)
        args = _ns("--repo", str(fixture_repo), "report", "--since", spec)
        assert commands.cmd_report(args) == 2
        assert "dorian report:" in capsys.readouterr().err


def test_cmd_revalidate_rejects_since_plus_changed_paths(
    fixture_repo: Path, tmp_path: Path, capsys
) -> None:
    listing = tmp_path / "changed.txt"
    listing.write_text("src/auth.py\n")
    argv = ["--since", "HEAD", "--changed-paths", str(listing)]
    args = _ns("--repo", str(fixture_repo), "revalidate", *argv)
    assert commands.cmd_revalidate(args) == 2
    assert "dorian revalidate:" in capsys.readouterr().err


def test_cmd_revalidate_bad_changed_paths_file_is_usage(
    fixture_repo: Path, tmp_path: Path, capsys
) -> None:
    """User-input failures are usage errors (exit 2), never 'corrupt sidecar' (4)."""
    binary = tmp_path / "changed.bin"
    binary.write_bytes(b"\xff\xfe\x00not-utf8")
    args = _ns("--repo", str(fixture_repo), "revalidate", "--changed-paths", str(binary))
    assert commands.cmd_revalidate(args) == 2
    err = capsys.readouterr().err
    assert "dorian revalidate:" in err
    assert "corrupt warrant sidecar" not in err

    missing = tmp_path / "nope.txt"
    args = _ns("--repo", str(fixture_repo), "revalidate", "--changed-paths", str(missing))
    assert commands.cmd_revalidate(args) == 2
    err = capsys.readouterr().err
    assert "dorian revalidate:" in err
    assert "corrupt warrant sidecar" not in err


def test_cmd_revalidate_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    """A nonexistent --repo is a usage error (exit 2): store.connect's mkdir
    raises FileNotFoundError (an OSError) which must not be mislabeled a
    'corrupt warrant sidecar' integrity revocation (exit 4)."""
    args = _ns("--repo", str(tmp_path / "nope"), "revalidate", "--since", "HEAD")
    assert commands.cmd_revalidate(args) == 2
    err = capsys.readouterr().err
    assert "dorian revalidate:" in err
    assert "corrupt warrant sidecar" not in err


def test_cmd_report_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    """cmd_report on a nonexistent --repo is usage (exit 2), not a traceback."""
    args = _ns("--repo", str(tmp_path / "nope"), "report", "--since", "7d")
    assert commands.cmd_report(args) == 2
    assert "dorian report:" in capsys.readouterr().err


def test_cmd_revalidate_reads_listing_exactly_once(
    fixture_repo: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    """The --changed-paths listing is read once: a validate-then-reread pattern
    would let the file vanish between reads and surface the second failure as a
    'corrupt warrant sidecar' (and reads a large listing twice)."""
    listing = tmp_path / "changed.txt"
    listing.write_text("src/util.py\n")
    reads: list[Path] = []
    real_read_text = Path.read_text

    def counting(self: Path, *a, **kw):
        if self == listing:
            reads.append(self)
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", counting)
    args = _ns("--repo", str(fixture_repo), "revalidate", "--changed-paths", str(listing))
    assert commands.cmd_revalidate(args) == 0
    capsys.readouterr()
    assert len(reads) == 1


def test_cmd_status_artifact_outside_repo_is_usage(fixture_repo: Path, capsys) -> None:
    """'dorian status /etc/hosts' must be a clean usage error (exit 2), not an
    uncaught ValueError traceback from _artifact_uri."""
    args = _ns("--repo", str(fixture_repo), "status", "/etc/hosts")
    assert commands.cmd_status(args) == 2
    err = capsys.readouterr().err
    assert "dorian status:" in err
    assert "outside repo" in err


def test_cmd_status_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    """A nonexistent --repo must exit 2 with a message, not raise
    FileNotFoundError from store.connect's mkdir."""
    args = _ns("--repo", str(tmp_path / "nope"), "status")
    assert commands.cmd_status(args) == 2
    err = capsys.readouterr().err
    assert "dorian status:" in err
    assert "corrupt warrant sidecar" not in err


def test_cmd_sync_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    args = _ns("--repo", str(tmp_path / "nope"), "sync")
    assert commands.cmd_sync(args) == 2
    err = capsys.readouterr().err
    assert "dorian sync:" in err
    assert "corrupt warrant sidecar" not in err


def test_cmd_capture_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    args = _ns("--repo", str(tmp_path / "nope"), "capture", "--manual", "src/x.py")
    assert commands.cmd_capture(args) == 2
    assert "dorian capture:" in capsys.readouterr().err


def test_cmd_seal_missing_repo_is_usage(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    """Valid readset + claims files but a nonexistent --repo: usage (exit 2),
    never an uncaught error or a misleading seal refusal (exit 4)."""
    rs = tmp_path / "rs.json"
    parse_manual(["src/auth.py"], fixture_repo).dump(rs)
    claims_path = tmp_path / "claims.json"
    claims_io.save_claims(claims_path, [Claim(id="c0", text="t", kind="fact", load_bearing=False)])
    args = _ns(
        "--repo",
        str(tmp_path / "nope"),
        "seal",
        "doc.md",
        "--readset",
        str(rs),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 2
    assert "dorian seal:" in capsys.readouterr().err


def test_cmd_status_json(fixture_repo: Path, capsys) -> None:
    """The global --json flag must emit a machine-readable status payload."""
    w = _sealed(fixture_repo)
    args = _ns("--json", "--repo", str(fixture_repo), "status")
    assert commands.cmd_status(args) == 0
    data = json.loads(capsys.readouterr().out)
    (entry,) = data["warrants"]
    assert entry["id"] == w.id
    assert entry["artifact_uri"] == "docs/design.md"
    assert entry["trust_state"] == "WARRANTED"
    assert entry["claim_states"] == {"VERIFIED": 4}


def test_cmd_report_json(fixture_repo: Path, capsys) -> None:
    """The global --json flag must emit a machine-readable report payload."""
    w = _sealed(fixture_repo)
    args = _ns("--json", "--repo", str(fixture_repo), "report", "--since", "7d")
    assert commands.cmd_report(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["since"] == "7d"
    (entry,) = data["warrants"]
    assert entry["warrant_id"] == w.id
    assert entry["artifact_uri"] == "docs/design.md"
    assert [e["kind"] for e in entry["events"]] == ["sealed"]


# --- (e) perf smoke --------------------------------------------------------------


def test_perf_smoke_200_warrants(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    for i in range(200):
        src = f"src/f{i}.txt"
        content = f"alpha {i}\nbeta\ngamma\n"
        write(repo, src, content)
        entry = ReadSetEntry(
            id="rs-0", uri=src, selector=None, hash=sha256_hex(content.encode()), version=None
        )
        claims = tuple(
            Claim(
                id=f"c{j}",
                text=f"claim {j} about {src}",
                kind="fact",
                load_bearing=False,
                supports=("rs-0",),
                checkers=(CheckerSpec(type="C1", program="rs-0", watch=(src,)),),
            )
            for j in range(5)
        )
        w = Warrant.create(
            artifact_uri=f"docs/g{i}.md",
            artifact_hash=sha256_hex(b"artifact"),
            git_ref="",
            produced_by=ProducedBy(runner="bench-synthetic", captured_at="2026-01-01T00:00:00Z"),
            read_set=(entry,),
            claims=claims,
            fold_policy=FoldPolicy(),
            sealed_at="2026-01-01T00:00:00Z",
        )
        w.dump(w.sidecar_path(repo))

    conn = store.connect(repo)
    try:
        assert store.sync(repo, conn) == 200
    finally:
        conn.close()

    changed = tmp_path / "changed.txt"
    changed.write_text("src/f0.txt\nsrc/f1.txt\nsrc/f2.txt\n")
    t0 = time.perf_counter()
    res = revalidate(repo, changed_paths_file=changed)
    wall = time.perf_counter() - t0

    assert res.candidates == 15  # 3 files x 5 claims each
    assert len(res.passed) == 15
    assert res.broken == res.errored == res.relocated == []
    assert res.exit_code == 0
    assert wall < 5.0, f"revalidate took {wall:.2f}s"


# --- (f) errored pathway -----------------------------------------------------------


def test_unrunnable_checker_is_errored_never_broken(tmp_path: Path) -> None:
    """Verdict discipline through revalidate: a checker that cannot run (here an
    unregistered type, as from a newer spec version) lands the claim in ERRORED,
    folds the warrant to UNKNOWN, and exits 5 — it must never count as BROKEN."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    src = "src/f.txt"
    content = "alpha\n"
    write(repo, src, content)
    entry = ReadSetEntry(
        id="rs-0", uri=src, selector=None, hash=sha256_hex(content.encode()), version=None
    )
    claim = Claim(
        id="c0",
        text="claim backed by a checker type this kernel cannot run",
        kind="fact",
        load_bearing=False,
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C9", program="rs-0", watch=(src,)),),
    )
    w = Warrant.create(
        artifact_uri="docs/g.md",
        artifact_hash=sha256_hex(b"artifact"),
        git_ref="",
        produced_by=ProducedBy(runner="bench-synthetic", captured_at="2026-01-01T00:00:00Z"),
        read_set=(entry,),
        claims=(claim,),
        fold_policy=FoldPolicy(),
        sealed_at="2026-01-01T00:00:00Z",
    )
    w.dump(w.sidecar_path(repo))
    conn = store.connect(repo)
    try:
        assert store.sync(repo, conn) == 1
    finally:
        conn.close()

    changed = tmp_path / "changed.txt"
    changed.write_text(f"{src}\n")
    res = revalidate(repo, changed_paths_file=changed)

    assert res.candidates == 1
    assert [(wid, cid) for wid, cid, _ in res.errored] == [(w.id, "c0")]
    assert all(detail for _, _, detail in res.errored)
    assert res.broken == res.relocated == res.passed == []
    assert res.folds == {w.id: ("WARRANTED", "UNKNOWN")}
    assert res.exit_code == 5

    conn = store.connect(repo)
    try:
        states = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w.id)}
        trust = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()[
            "trust_state"
        ]
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM event ORDER BY seq")]
    finally:
        conn.close()
    assert states == {"c0": "ERRORED"}
    assert trust == "UNKNOWN"
    assert kinds.count("claim.stale") == 1
    assert kinds.count("claim.errored") == 1
    assert kinds.count("fold.unknown") == 1
    assert "claim.broken" not in kinds

    assert "ERRORED" in render_text(res)
    data = json.loads(render_json(res))
    assert [e[:2] for e in data["errored"]] == [[w.id, "c0"]]
    assert data["exit_code"] == 5


# --- (g) non-load-bearing break -> DEGRADED, exit 3 --------------------------------


def test_non_load_bearing_break_degrades_exit_3(fixture_repo: Path) -> None:
    """Only the non-load-bearing login claim breaks: the default FoldPolicy
    (revoke_on='load_bearing_broken') must fold DEGRADED — not REVOKED, and
    never silently exit 0 — mapping to exit 3."""
    w = _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""))

    res = revalidate(fixture_repo, since=base)
    assert res.candidates == 1  # only c3 binds src/routes.py
    assert [(wid, cid) for wid, cid, _ in res.broken] == [(w.id, "c3")]
    assert res.relocated == res.errored == res.passed == []
    assert res.folds == {w.id: ("WARRANTED", "DEGRADED")}
    assert res.exit_code == 3

    conn = store.connect(fixture_repo)
    try:
        states = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w.id)}
        trust = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()[
            "trust_state"
        ]
    finally:
        conn.close()
    assert states == {"c1": "VERIFIED", "c2": "VERIFIED", "c3": "BROKEN", "c4": "VERIFIED"}
    assert trust == "DEGRADED"
    kinds = _audit_kinds(fixture_repo)
    assert kinds.count("claim.broken") == 1
    assert kinds.count("fold.degraded") == 1
    assert "fold.revoked" not in kinds


# --- (h) unbacked candidate claim ---------------------------------------------------


def test_unbacked_claim_candidate_stays_unbacked(tmp_path: Path) -> None:
    """A candidate claim with no checkers is marked stale but never re-stated:
    state stays UNBACKED (no fabricated VERIFIED/BROKEN), the fold ignores it
    (WARRANTED -> TRUSTED), exit 0."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    src = "src/f.txt"
    content = "alpha\n"
    write(repo, src, content)
    entry = ReadSetEntry(
        id="rs-0", uri=src, selector=None, hash=sha256_hex(content.encode()), version=None
    )
    claim = Claim(
        id="c0",
        text="an unbacked claim about src/f.txt",
        kind="fact",
        load_bearing=True,
        supports=("rs-0",),
    )
    w = Warrant.create(
        artifact_uri="docs/g.md",
        artifact_hash=sha256_hex(b"artifact"),
        git_ref="",
        produced_by=ProducedBy(runner="bench-synthetic", captured_at="2026-01-01T00:00:00Z"),
        read_set=(entry,),
        claims=(claim,),
        fold_policy=FoldPolicy(),
        sealed_at="2026-01-01T00:00:00Z",
    )
    w.dump(w.sidecar_path(repo))
    conn = store.connect(repo)
    try:
        assert store.sync(repo, conn) == 1
    finally:
        conn.close()

    changed = tmp_path / "changed.txt"
    changed.write_text(f"{src}\n")
    res = revalidate(repo, changed_paths_file=changed)

    assert res.candidates == 1
    assert res.broken == res.relocated == res.errored == res.passed == []
    assert res.exit_code == 0

    conn = store.connect(repo)
    try:
        states = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w.id)}
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM event ORDER BY seq")]
    finally:
        conn.close()
    assert states == {"c0": "UNBACKED"}  # preserved, never fabricated VERIFIED
    assert kinds.count("claim.stale") == 1
    assert not any(k in kinds for k in ("claim.verified", "claim.broken", "claim.errored"))
    assert res.folds == {w.id: ("WARRANTED", "TRUSTED")}  # fold ignores UNBACKED


# --- (i) recall flags: broken claim -> recalled events downstream --------------------


def test_broken_claim_recalls_downstream(fixture_repo: Path) -> None:
    """Break c2 in A (the TIMEOUT claim) with B and C sealed downstream
    (B reads A's artifact, C reads B's): both get a 'recalled' event flag —
    and nothing else: no re-check, no claim/trust state change downstream,
    and the exit code still reflects only the touched warrants."""
    w_a = _sealed(fixture_repo)
    write(fixture_repo, "docs/b.md", "# B\n\nBuilds on docs/design.md.\n")
    claims_b = [
        Claim(
            id="b1",
            text="The design doc mentions RS256.",
            kind="reference",
            load_bearing=False,
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C3", program="string:docs/design.md::RS256"),),
        )
    ]
    rs_b = parse_manual(["docs/design.md"], fixture_repo)
    w_b = seal_artifact(fixture_repo, "docs/b.md", rs_b, claims_b)
    write(fixture_repo, "docs/c.md", "# C\n\nBuilds on docs/b.md.\n")
    w_c = seal_artifact(fixture_repo, "docs/c.md", parse_manual(["docs/b.md"], fixture_repo), [])
    commit_all(fixture_repo, "seal chain A <- B <- C")

    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))

    res = revalidate(fixture_repo, since=base)
    assert [(wid, cid) for wid, cid, _ in res.broken] == [(w_a.id, "c2")]
    assert res.exit_code == 4  # exit semantics unchanged by recall flags
    assert [(e["warrant_id"], e["artifact_uri"], e["depth"], e["via"]) for e in res.recalled] == [
        (w_b.id, "docs/b.md", 1, w_a.id),
        (w_c.id, "docs/c.md", 2, w_a.id),
    ]

    conn = store.connect(fixture_repo)
    try:
        rows = conn.execute(
            "SELECT warrant_id, cause FROM event WHERE kind = 'recalled' ORDER BY seq"
        ).fetchall()
        assert [r["warrant_id"] for r in rows] == [w_b.id, w_c.id]
        assert [json.loads(r["cause"]) for r in rows] == [
            {"via": w_a.id, "claim_ids": ["c2"], "depth": 1},
            {"via": w_a.id, "claim_ids": ["c2"], "depth": 2},
        ]
        # downstream untouched: events are the whole deliverable
        states_b = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w_b.id)}
        assert states_b == {"b1": "VERIFIED"}
        for wid in (w_b.id, w_c.id):
            trust = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (wid,)).fetchone()[
                "trust_state"
            ]
            assert trust == "WARRANTED"
    finally:
        conn.close()

    assert "recalled: 2 downstream artifact(s)" in render_text(res)
    data = json.loads(render_json(res))
    assert [e["warrant_id"] for e in data["recalled"]] == [w_b.id, w_c.id]

    # second run: c2 is already BROKEN (not newly broken) -> no new recall flags
    res2 = revalidate(fixture_repo, since=base)
    assert [(wid, cid) for wid, cid, _ in res2.broken] == [(w_a.id, "c2")]
    assert res2.recalled == []
    conn = store.connect(fixture_repo)
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM event WHERE kind = 'recalled'").fetchone()["c"]
    finally:
        conn.close()
    assert n == 2


# --- (j) regex auto-watch regression -------------------------------------------------


def test_regex_checker_auto_watch_revalidates_end_to_end(fixture_repo: Path) -> None:
    """A watch-less C3 regex: checker must derive watch=(<file>,) at seal time.
    Regression: _derive_watch only split '<file>::<operand>' for symbol/string,
    so a regex checker got the junk watch '<file>::<pattern>' and revalidate
    silently skipped the claim (candidates=0) when the file changed — the v0.0
    unwatched-binding false-negative class through the grammar D2 recommends."""
    claim = Claim(
        id="r1",
        text="The default request timeout is 30 seconds.",
        kind="quantity",
        load_bearing=True,
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C3", program=r"regex:src/config.py::TIMEOUT\s*=\s*30"),),
    )
    rs = parse_manual(["src/config.py"], fixture_repo)
    w = seal_artifact(fixture_repo, "docs/design.md", rs, [claim])
    assert w.claims[0].checkers[0].watch == ("src/config.py",)
    # the dumped sidecar (source of truth) carries the derived watch too
    loaded = Warrant.load(fixture_repo / "docs/design.md.warrant")
    assert loaded.claims[0].checkers[0].watch == ("src/config.py",)

    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT=99"))
    commit_all(fixture_repo, "retune timeout")
    res = revalidate(fixture_repo, since=base)
    assert res.candidates == 1  # was 0 before the fix: claim silently never re-checked
    assert [(cid, detail) for _, cid, detail in res.broken] == [("r1", "C3: regex_missing")]
