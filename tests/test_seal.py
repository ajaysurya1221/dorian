"""Seal pipeline + CLI handler acceptance tests.

Matrix:
seal:
(a) e2e on fixture_repo: sidecar written, Warrant.load round-trips, store rows
    (warrant/resource/claim) present, claims VERIFIED, 'sealed' event recorded,
    no temp-file leftovers
(b) FAILED_AT_SEAL: config corrupted between capture and seal -> SealError,
    nothing written (no sidecar)
(c) checker ERROR at seal also refuses to seal (a warrant is born verifiable)
    and is reported as ERRORED_AT_SEAL, never conflated with FAILED_AT_SEAL
(d) auto-watch: C1 -> supports entry uri, C3 -> referenced file, C5 typed ->
    data path; C5 shell without explicit watch -> SealError
(e) derives_from: artifact B whose read-set includes sealed design.md derives
    from warrant A
(i) infra problems surface as SealError, not tracebacks: corrupt/tampered/
    wrong-shape input sidecar during derives_from scanning; repo with no
    commits (HEAD unresolvable)
(j) duplicate claim ids refuse to seal: the store PK would reject them only
    AFTER the sidecar exists, stranding a sidecar the index can never load
claims_io:
(f) save/load round-trip (incl. non-ASCII text); bad kind / bad checker type /
    duplicate id / malformed -> ValueError
extract:
(g) DORIAN_EXTRACT_STUB loads claims offline; no stub + no anthropic ->
    ExtractUnavailable; fake-anthropic path calls the API once and caches;
    a corrupt cache entry is dropped and re-extracted, not a permanent error
commands:
(h) capture/seal/status/sync handlers driven via cli.build_parser() exit codes;
    malformed (valid-JSON, wrong-shape) read-set file -> usage exit 2;
    corrupt sidecar anywhere -> status/sync print a message and exit 4, never a
    traceback; `seal --extract` refuses to overwrite an existing claims.json
    (exit 2) so re-extraction cannot clobber a manual review
"""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

from conftest import CONFIG_PY, git, write
from dorian import claims_io, cli, commands, extract, gitio, store
from dorian.capture.manual import parse_manual
from dorian.model import Anchor, CheckerSpec, Claim, ProducedBy, ReadSet, Warrant
from dorian.seal import SealError, seal_artifact

SPECS = ["src/auth.py:L4-7", "src/config.py:L1-1", "src/routes.py", "data/lots.csv"]

SHELL_PROGRAM = 'shell:grep -Eq "TIMEOUT *= *30" src/config.py'


def make_claims(*, shell_watch: tuple[str, ...] = ("src/config.py",)) -> list[Claim]:
    """The 4 demo claims over the fixture read-set (entries rs-0..rs-3)."""
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
            checkers=(CheckerSpec(type="C5", program=SHELL_PROGRAM, watch=shell_watch),),
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


# --- seal pipeline ---------------------------------------------------------------


def test_seal_end_to_end(fixture_repo: Path) -> None:
    rs = parse_manual(SPECS, fixture_repo)
    w = seal_artifact(fixture_repo, "docs/design.md", rs, make_claims())

    sidecar = fixture_repo / "docs/design.md.warrant"
    assert sidecar.is_file()
    assert not list(fixture_repo.rglob("*.tmp"))  # atomic write leaves no temp files
    loaded = Warrant.load(sidecar)  # integrity-checked round-trip
    assert loaded.id == w.id
    assert w.artifact_uri == "docs/design.md"
    assert w.git_ref == gitio.head_ref(fixture_repo)
    assert w.artifact_hash == gitio.working_hash(fixture_repo, "docs/design.md")
    assert len(w.read_set) == 4

    conn = store.connect(fixture_repo)
    try:
        row = conn.execute("SELECT * FROM warrant WHERE id = ?", (w.id,)).fetchone()
        assert row is not None
        assert row["trust_state"] == "WARRANTED"
        assert row["artifact_uri"] == "docs/design.md"
        n_res = conn.execute(
            "SELECT COUNT(*) AS c FROM resource WHERE warrant_id = ?", (w.id,)
        ).fetchone()["c"]
        assert n_res == 4
        states = store.get_claim_states(conn, w.id)
        assert len(states) == 4
        assert all(s["state"] == "VERIFIED" for s in states)
        kinds = [
            r["kind"] for r in conn.execute("SELECT kind FROM event WHERE warrant_id = ?", (w.id,))
        ]
        assert "sealed" in kinds
    finally:
        conn.close()


def test_failed_at_seal_writes_nothing(fixture_repo: Path) -> None:
    rs = parse_manual(SPECS, fixture_repo)  # captured while TIMEOUT = 30
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    with pytest.raises(SealError, match="FAILED_AT_SEAL: c2"):
        seal_artifact(fixture_repo, "docs/design.md", rs, make_claims())
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_checker_error_at_seal_refuses(fixture_repo: Path) -> None:
    """A checker ERROR at seal time also refuses: a warrant must be born verifiable."""
    rs = parse_manual(SPECS, fixture_repo)
    claims = [
        Claim(
            id="c1",
            text="anchored to a nonexistent read-set entry",
            kind="fact",
            load_bearing=True,
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-99", watch=("src/auth.py",)),),
        )
    ]
    # must be ERRORED_AT_SEAL: conflating checker ERROR into FAILED_AT_SEAL would
    # break the ERROR-vs-FAIL discipline that checkers/base.py calls load-bearing
    with pytest.raises(SealError, match="ERRORED_AT_SEAL: c1"):
        seal_artifact(fixture_repo, "docs/design.md", rs, claims)
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_auto_watch_derivation(fixture_repo: Path) -> None:
    rs = parse_manual(SPECS, fixture_repo)
    w = seal_artifact(fixture_repo, "docs/design.md", rs, make_claims())
    by_id = {c.id: c for c in w.claims}
    assert by_id["c1"].checkers[0].watch == ("src/auth.py",)  # C1: supports entry uri
    assert by_id["c2"].checkers[0].watch == ("src/config.py",)  # explicit, untouched
    assert by_id["c3"].checkers[0].watch == ("src/routes.py",)  # C3: referenced file
    assert by_id["c4"].checkers[0].watch == ("data/lots.csv",)  # C5 typed: data path
    # and the dumped sidecar carries the derived watches
    loaded = Warrant.load(fixture_repo / "docs/design.md.warrant")
    assert {c.id: c for c in loaded.claims}["c1"].checkers[0].watch == ("src/auth.py",)


def test_auto_watch_derivation_c4(fixture_repo: Path) -> None:
    """Regression: C4 once had no _derive_watch branch, so a checker sealed
    without an explicit watch got watch=() silently — never a revalidate
    candidate, a permanent false negative. The nodeid's file part is the watch
    (mirroring C3); explicit watches stay untouched."""
    from dorian.seal import _derive_watch

    rs = parse_manual(SPECS, fixture_repo)
    derived = _derive_watch(
        CheckerSpec(type="C4", program="pytest:tests/test_x.py::test_alpha"), rs
    )
    assert derived.watch == ("tests/test_x.py",)
    # whole-file nodeid (a bare path is a valid pytest nodeid)
    assert _derive_watch(CheckerSpec(type="C4", program="pytest:tests/test_x.py"), rs).watch == (
        "tests/test_x.py",
    )
    explicit = CheckerSpec(type="C4", program="pytest:tests/test_x.py::t", watch=("custom.py",))
    assert _derive_watch(explicit, rs).watch == ("custom.py",)


def test_c5_shell_requires_explicit_watch(fixture_repo: Path) -> None:
    rs = parse_manual(SPECS, fixture_repo)
    with pytest.raises(SealError, match="C5 shell checker requires watch"):
        seal_artifact(fixture_repo, "docs/design.md", rs, make_claims(shell_watch=()))
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_derives_from_sealed_inputs(fixture_repo: Path) -> None:
    rs_a = parse_manual(SPECS, fixture_repo)
    w_a = seal_artifact(fixture_repo, "docs/design.md", rs_a, make_claims())

    write(fixture_repo, "docs/summary.md", "# Summary\n\nSee docs/design.md.\n")
    rs_b = parse_manual(["docs/design.md", "data/lots.csv"], fixture_repo)
    w_b = seal_artifact(fixture_repo, "docs/summary.md", rs_b, [])
    assert w_b.derives_from == (w_a.id,)


def test_seal_refuses_corrupt_input_sidecar(fixture_repo: Path) -> None:
    """A tampered or garbage sidecar found during derives_from scanning is a clean
    SealError naming the sidecar, never an IntegrityError/JSONDecodeError traceback."""
    rs_a = parse_manual(SPECS, fixture_repo)
    seal_artifact(fixture_repo, "docs/design.md", rs_a, make_claims())
    sidecar = fixture_repo / "docs/design.md.warrant"

    write(fixture_repo, "docs/summary.md", "# Summary\n\nSee docs/design.md.\n")
    rs_b = parse_manual(["docs/design.md"], fixture_repo)

    # tampered: body edited so the content-addressed id no longer matches
    d = json.loads(sidecar.read_text())
    d["warrant"]["sealed_at"] = "1999-01-01T00:00:00Z"
    sidecar.write_text(json.dumps(d))
    with pytest.raises(SealError, match=r"docs/design\.md\.warrant"):
        seal_artifact(fixture_repo, "docs/summary.md", rs_b, [])
    assert not (fixture_repo / "docs/summary.md.warrant").exists()

    # outright garbage (not JSON at all)
    sidecar.write_text("not json {")
    with pytest.raises(SealError, match=r"docs/design\.md\.warrant"):
        seal_artifact(fixture_repo, "docs/summary.md", rs_b, [])
    assert not (fixture_repo / "docs/summary.md.warrant").exists()

    # valid JSON, wrong shape: Warrant.from_dict raises TypeError ('artifact' is
    # a string where an object is expected), which must also become SealError
    sidecar.write_text(json.dumps({"warrant": {"id": "x", "artifact": "nope"}}))
    with pytest.raises(SealError, match=r"docs/design\.md\.warrant"):
        seal_artifact(fixture_repo, "docs/summary.md", rs_b, [])
    assert not (fixture_repo / "docs/summary.md.warrant").exists()


def test_seal_refuses_duplicate_claim_ids(fixture_repo: Path) -> None:
    """Duplicate claim ids must refuse BEFORE the sidecar is written: the store's
    (warrant_id, claim_id) PK only rejects them after, stranding a sidecar that
    breaks every subsequent sync until hand-deleted."""
    rs = parse_manual(SPECS, fixture_repo)
    dup = Claim(id="c1", text="duplicated id", kind="fact", load_bearing=False)
    with pytest.raises(SealError, match="duplicate claim id"):
        seal_artifact(fixture_repo, "docs/design.md", rs, [dup, dup])
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_seal_refuses_repo_without_commits(tmp_path: Path) -> None:
    """HEAD unresolvable (fresh repo, no commits) is a clean SealError, not GitError."""
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "note.md", "hello\n")
    rs = ReadSet(
        entries=(),
        produced_by=ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z"),
    )
    with pytest.raises(SealError, match="HEAD"):
        seal_artifact(repo, "note.md", rs, [])
    assert not (repo / "note.md.warrant").exists()


# --- claims_io -------------------------------------------------------------------


def test_claims_io_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    # include non-ASCII text: save/load must be UTF-8 regardless of locale
    claims = [
        *make_claims(),
        Claim(id="c5", text="Latence médiane ≤ 30 ms — vérifié ✓", kind="fact", load_bearing=False),
    ]
    claims_io.save_claims(path, claims)
    assert claims_io.load_claims(path) == claims


def test_claims_io_rejects_bad_kind(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    path.write_text(
        json.dumps({"claims": [{"id": "c1", "text": "t", "kind": "vibe", "load_bearing": True}]})
    )
    with pytest.raises(ValueError, match="kind"):
        claims_io.load_claims(path)


def test_claims_io_rejects_bad_checker_type(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    path.write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "c1",
                        "text": "t",
                        "kind": "fact",
                        "load_bearing": False,
                        "checkers": [{"type": "C9", "program": "path:x"}],
                    }
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="C9"):
        claims_io.load_claims(path)


def test_claims_io_rejects_duplicate_ids(tmp_path: Path) -> None:
    """LLM extraction plausibly emits duplicate ids; they must die in validation,
    not as a sqlite3.IntegrityError after the sidecar is already on disk."""
    path = tmp_path / "claims.json"
    claim = {"id": "c1", "text": "t", "kind": "fact", "load_bearing": False}
    path.write_text(json.dumps({"claims": [claim, claim]}))
    with pytest.raises(ValueError, match="duplicate claim id"):
        claims_io.load_claims(path)


def test_claims_io_rejects_malformed(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    path.write_text("not json {")
    with pytest.raises(ValueError):
        claims_io.load_claims(path)
    path.write_text(json.dumps({"claims": [{"id": "c1"}]}))  # missing required fields
    with pytest.raises(ValueError):
        claims_io.load_claims(path)
    path.write_text(json.dumps(["c1"]))  # wrong top-level shape
    with pytest.raises(ValueError):
        claims_io.load_claims(path)


# --- extract ---------------------------------------------------------------------


def test_extract_stub_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = tmp_path / "stub-claims.json"
    claims_io.save_claims(stub, make_claims())
    monkeypatch.setenv("DORIAN_EXTRACT_STUB", str(stub))
    got = extract.extract_claims(
        "anything", model="m", cache_dir=tmp_path / "cache", artifact_hash="sha256:x"
    )
    assert got == make_claims()


def test_extract_unavailable_without_anthropic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", None)  # force ImportError
    with pytest.raises(extract.ExtractUnavailable, match=r"dorian-vwp\[extract\]"):
        extract.extract_claims(
            "text", model="m", cache_dir=tmp_path / "cache", artifact_hash="sha256:x"
        )


_EXTRACT_PAYLOAD = {
    "claims": [
        {
            "id": "c1",
            "text": "extracted",
            "kind": "fact",
            "load_bearing": True,
            "anchor": None,
            "supports": [],
            "checkers": [],
        }
    ]
}


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Install a fake `anthropic` module returning _EXTRACT_PAYLOAD; returns the
    call-recording list."""
    calls: list[dict] = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            block = types.SimpleNamespace(
                type="tool_use", name="emit_claims", input=_EXTRACT_PAYLOAD
            )
            return types.SimpleNamespace(content=[block], stop_reason="tool_use")

    class _Anthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def test_extract_calls_api_once_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    calls = _install_fake_anthropic(monkeypatch)

    cache_dir = tmp_path / "cache"
    kwargs = {"model": "m", "cache_dir": cache_dir, "artifact_hash": "sha256:x"}
    first = extract.extract_claims("artifact text", **kwargs)
    assert [c.id for c in first] == ["c1"]
    assert len(calls) == 1
    assert calls[0]["system"] == extract.PROMPT_V0
    assert len(list(cache_dir.iterdir())) == 1

    second = extract.extract_claims("artifact text", **kwargs)  # served from cache
    assert second == first
    assert len(calls) == 1


def test_extract_corrupt_cache_is_dropped_and_refetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupted cache file is not a permanent failure: it is discarded and the
    extraction re-runs (and re-caches)."""
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    calls = _install_fake_anthropic(monkeypatch)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    extract._cache_path(cache_dir, "sha256:x", "m").write_text("corrupt {")

    kwargs = {"model": "m", "cache_dir": cache_dir, "artifact_hash": "sha256:x"}
    got = extract.extract_claims("artifact text", **kwargs)
    assert [c.id for c in got] == ["c1"]
    assert len(calls) == 1

    # cache healed: second call is served without another API call
    assert extract.extract_claims("artifact text", **kwargs) == got
    assert len(calls) == 1


# --- command handlers ------------------------------------------------------------


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _capture_argv(repo: Path, out: Path) -> list[str]:
    argv = ["--repo", str(repo), "capture"]
    for spec in SPECS:
        argv += ["--manual", spec]
    return [*argv, "--out", str(out)]


def test_cmd_capture_manual(fixture_repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "rs.json"
    assert commands.cmd_capture(_ns(*_capture_argv(fixture_repo, out))) == 0
    rs = ReadSet.load(out)
    assert [e.uri for e in rs.entries] == [
        "src/auth.py",
        "src/config.py",
        "src/routes.py",
        "data/lots.csv",
    ]


def test_cmd_capture_requires_exactly_one_source(fixture_repo: Path, tmp_path: Path) -> None:
    assert commands.cmd_capture(_ns("--repo", str(fixture_repo), "capture")) == 2
    args = _ns(
        "--repo",
        str(fixture_repo),
        "capture",
        "--transcript",
        "session.jsonl",
        "--manual",
        "src/auth.py",
    )
    assert commands.cmd_capture(args) == 2


def test_cmd_capture_stdin(
    fixture_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "rs.json"
    monkeypatch.setattr(sys, "stdin", io.StringIO("src/routes.py\ndata/lots.csv\n"))
    args = _ns("--repo", str(fixture_repo), "capture", "--stdin", "--out", str(out))
    assert commands.cmd_capture(args) == 0
    assert len(ReadSet.load(out).entries) == 2


def _seal_setup(repo: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Capture a read-set + write claims.json; return (rs_path, claims_path)."""
    rs_path, claims_path = tmp_path / "rs.json", tmp_path / "claims.json"
    parse_manual(SPECS, repo).dump(rs_path)
    claims_io.save_claims(claims_path, make_claims())
    return rs_path, claims_path


def test_cmd_seal_status_sync(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    rs_path, claims_path = _seal_setup(fixture_repo, tmp_path)
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 0
    assert (fixture_repo / "docs/design.md.warrant").is_file()

    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status")) == 0
    out = capsys.readouterr().out
    assert "WARRANTED" in out
    assert "docs/design.md" in out
    assert "VERIFIED=4" in out

    assert commands.cmd_sync(_ns("--repo", str(fixture_repo), "sync")) == 0


def test_cmd_status_check_reports_drift(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    rs_path, claims_path = _seal_setup(fixture_repo, tmp_path)
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 0
    capsys.readouterr()

    # no drift yet
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status", "--check")) == 0
    assert "drifted" not in capsys.readouterr().out

    # drift the config span; kernel --check reports it without running checkers
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    rc = commands.cmd_status(_ns("--repo", str(fixture_repo), "status", "--check"))
    assert rc == 0  # trust_state untouched by --check in the kernel
    out = capsys.readouterr().out
    assert out.count("drifted") == 1
    assert "src/config.py" in out


def test_cmd_seal_failure_exits_4(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    rs_path, claims_path = _seal_setup(fixture_repo, tmp_path)
    write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 4
    assert "FAILED_AT_SEAL" in capsys.readouterr().err
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_cmd_seal_malformed_readset_exits_2(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    """Valid JSON but wrong shape ({}: no 'entries') is a usage error (2), not a
    KeyError traceback."""
    rs_path = tmp_path / "rs.json"
    rs_path.write_text("{}")
    claims_path = tmp_path / "claims.json"
    claims_io.save_claims(claims_path, make_claims())
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 2
    assert "dorian seal:" in capsys.readouterr().err


def test_cmd_seal_corrupt_input_sidecar_exits_4(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    """A corrupt sidecar met during derives_from scanning exits 4 with a message,
    not an IntegrityError/JSONDecodeError traceback."""
    rs_path, claims_path = _seal_setup(fixture_repo, tmp_path)
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 0
    (fixture_repo / "docs/design.md.warrant").write_text("garbage")

    write(fixture_repo, "docs/summary.md", "# Summary\n\nSee docs/design.md.\n")
    rs2_path = tmp_path / "rs2.json"
    parse_manual(["docs/design.md"], fixture_repo).dump(rs2_path)
    claims2_path = tmp_path / "claims2.json"
    claims_io.save_claims(claims2_path, [])
    args2 = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/summary.md",
        "--readset",
        str(rs2_path),
        "--claims",
        str(claims2_path),
    )
    capsys.readouterr()
    assert commands.cmd_seal(args2) == 4
    assert "dorian seal:" in capsys.readouterr().err
    assert not (fixture_repo / "docs/summary.md.warrant").exists()


def test_cmd_status_sync_corrupt_sidecar_exit_4(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    """A corrupt or tampered sidecar anywhere in the repo turns status/sync into a
    clean stderr message + exit 4 (integrity), never a JSONDecodeError or
    IntegrityError traceback -- status is the diagnostic command, so it must not
    die of the disease it diagnoses."""
    rs_path, claims_path = _seal_setup(fixture_repo, tmp_path)
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--claims",
        str(claims_path),
    )
    assert commands.cmd_seal(args) == 0
    sidecar = fixture_repo / "docs/design.md.warrant"
    original = sidecar.read_text()
    capsys.readouterr()

    # outright garbage (not JSON)
    sidecar.write_text("garbage {")
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status")) == 4
    assert "dorian status:" in capsys.readouterr().err
    assert commands.cmd_sync(_ns("--repo", str(fixture_repo), "sync")) == 4
    assert "dorian sync:" in capsys.readouterr().err

    # tampered: valid JSON whose content-addressed id no longer matches
    d = json.loads(original)
    d["warrant"]["sealed_at"] = "1999-01-01T00:00:00Z"
    sidecar.write_text(json.dumps(d))
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status")) == 4
    assert "dorian status:" in capsys.readouterr().err

    # restoring the sidecar restores status
    sidecar.write_text(original)
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status")) == 0


def test_cmd_seal_extract_refuses_to_overwrite_claims(
    fixture_repo: Path, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running --extract with a claims.json already next to the artifact must
    refuse (exit 2) rather than clobber the manual review the file embodies."""
    rs_path, _ = _seal_setup(fixture_repo, tmp_path)
    stub = tmp_path / "stub-claims.json"
    claims_io.save_claims(stub, make_claims())
    monkeypatch.setenv("DORIAN_EXTRACT_STUB", str(stub))
    reviewed = fixture_repo / "docs/claims.json"
    claims_io.save_claims(
        reviewed, [Claim(id="c9", text="manually-reviewed", kind="fact", load_bearing=False)]
    )
    edited = reviewed.read_text()
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--extract",
    )
    assert commands.cmd_seal(args) == 2
    assert "claims.json" in capsys.readouterr().err
    assert reviewed.read_text() == edited  # manual edits preserved
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_cmd_seal_missing_claims_source(fixture_repo: Path, tmp_path: Path) -> None:
    rs_path, _ = _seal_setup(fixture_repo, tmp_path)
    args = _ns("--repo", str(fixture_repo), "seal", "docs/design.md", "--readset", str(rs_path))
    assert commands.cmd_seal(args) == 2


def test_cmd_seal_extract_review_loop(
    fixture_repo: Path, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    rs_path, _ = _seal_setup(fixture_repo, tmp_path)
    stub = tmp_path / "stub-claims.json"
    claims_io.save_claims(stub, make_claims())
    monkeypatch.setenv("DORIAN_EXTRACT_STUB", str(stub))
    args = _ns(
        "--repo",
        str(fixture_repo),
        "seal",
        "docs/design.md",
        "--readset",
        str(rs_path),
        "--extract",
    )
    assert commands.cmd_seal(args) == 0
    assert "review claims.json then re-run with --claims" in capsys.readouterr().out
    written = fixture_repo / "docs/claims.json"
    assert written.is_file()
    assert claims_io.load_claims(written) == make_claims()
    assert not (fixture_repo / "docs/design.md.warrant").exists()  # no sealing yet
