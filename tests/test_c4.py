"""Acceptance for the C4 test-binding checker (pytest:<nodeid> grammar).

Each scenario drives a real `python -m pytest` subprocess against a tiny fixture
repo, so those tests are marked slow (they still run by default; deselect with
-m 'not slow'). Exit-code mapping under test (probed against pytest 9.0.3):
0 PASS, 1 FAIL(test_failing), 5 FAIL(test_gone), 2/3/timeout/spawn ERROR.
Exit 4 (UsageError) is disambiguated by stderr signature: the nodeid-gone
messages ("ERROR: file or directory not found" / "ERROR: not found:") are
FAIL(test_gone); anything else on exit 4 (broken conftest, bad ini/plugin,
unimportable nodeid-targeted file) is infrastructure -> ERROR, never FAIL.
Exit 1 has one impostor: empty stdout + "No module named pytest" on stderr
(a PATH python whose env lacks pytest) is ERROR(pytest_missing), never FAIL.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import commit_all, git, write
from dorian import claims_io, cli, commands, revalidate
from dorian.checkers import c4_test as c4_mod
from dorian.checkers.base import CheckContext, CheckResult, Verdict, run_checker
from dorian.model import CheckerSpec, Claim, ProducedBy, ReadSet
from dorian.policy import ExecutionPolicy
from dorian.seal import SealError, seal_artifact

MINI = "tests/test_mini.py"

MINI_TESTS = """import time


def test_green():
    assert 1 + 1 == 2


def test_red():
    assert 1 + 1 == 3


def test_sleepy():
    time.sleep(5)
    assert True
"""

BROKEN_IMPORT = """import nonexistent_module_dorian_c4


def test_unreachable():
    assert True
"""


@pytest.fixture(autouse=True)
def _interpreter_on_path(monkeypatch):
    """Keep this suite invocation-insensitive: the checker spawns bare `python`
    against a stripped env, so without venv activation (e.g. running the suite
    as `.venv/bin/python -m pytest`) PATH may resolve no `python` at all.
    Prepend the running interpreter's bin dir so spawned-pytest verdicts don't
    depend on how this suite itself was invoked."""
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent), prepend=os.pathsep)


@pytest.fixture
def c4_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, MINI, MINI_TESTS)
    write(repo, "tests/test_broken.py", BROKEN_IMPORT)
    write(repo, "docs/note.md", "The mini suite stays green.\n")
    commit_all(repo, "initial mini test suite")
    return repo


def run_c4(
    repo: Path, program: str, *, timeout_s: int = 30, rename_map: dict[str, str] | None = None
) -> CheckResult:
    spec = CheckerSpec(type="C4", program=program, timeout_s=timeout_s)
    claim = Claim(
        id="cl1", text="behavior claim", kind="behavior", load_bearing=True, checkers=(spec,)
    )
    ctx = CheckContext(repo=repo, claim=claim, rename_map=dict(rename_map or {}))
    return run_checker(ctx, 0)


# --- verdicts from real pytest runs ----------------------------------------------


@pytest.mark.slow
def test_green_test_passes(c4_repo):
    assert run_c4(c4_repo, f"pytest:{MINI}::test_green").verdict is Verdict.PASS


@pytest.mark.slow
def test_failing_assert_is_fail_test_failing(c4_repo):
    res = run_c4(c4_repo, f"pytest:{MINI}::test_red")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "test_failing"


@pytest.mark.slow
def test_deleted_test_file_is_fail_test_gone(c4_repo):
    res = run_c4(c4_repo, "pytest:tests/test_deleted.py::test_x")  # exit 4: file not found
    assert res.verdict is Verdict.FAIL
    assert res.detail == "test_gone"


@pytest.mark.slow
def test_nonexistent_nodeid_is_fail_test_gone(c4_repo):
    res = run_c4(c4_repo, f"pytest:{MINI}::test_vanished")  # exit 4: nodeid not found
    assert res.verdict is Verdict.FAIL
    assert res.detail == "test_gone"


@pytest.mark.slow
def test_import_error_via_nodeid_is_error(c4_repo):
    # pytest 9.0.3 reports a collection error behind a full nodeid as
    # "ERROR: found no collectors" with exit code 4. The test FILE still
    # exists and the import failure may be pure environment (a dependency
    # missing in the checker's stripped env), so this is ERROR, not
    # FAIL(test_gone) — same judgment as the whole-file exit-2 case below.
    res = run_c4(c4_repo, "pytest:tests/test_broken.py::test_unreachable")
    assert res.verdict is Verdict.ERROR


@pytest.mark.slow
def test_broken_conftest_is_error_not_test_gone(c4_repo):
    """Regression: ALL pytest exit-4 UsageErrors once mapped to FAIL(test_gone),
    so a broken conftest.py (pure infrastructure; the bound test untouched and
    green-able) reported BROKEN, folded TRUSTED->DEGRADED, and recalled
    downstream warrants — infra dressed as staleness, the exact false-positive
    class the product exists to kill. It must be ERROR."""
    write(c4_repo, "conftest.py", "import nonexistent_conftest_dep_dorian_c4\n")
    res = run_c4(c4_repo, f"pytest:{MINI}::test_green")
    assert res.verdict is Verdict.ERROR
    assert res.detail != "test_gone"


@pytest.mark.slow
def test_bad_ini_is_error_not_test_gone(c4_repo):
    """A malformed pytest config (exit 4, "ERROR: usage:") is infrastructure."""
    write(c4_repo, "pytest.ini", "[pytest]\naddopts = --bogus-flag-dorian\n")
    res = run_c4(c4_repo, f"pytest:{MINI}::test_green")
    assert res.verdict is Verdict.ERROR
    assert res.detail != "test_gone"


@pytest.mark.slow
def test_import_error_whole_file_is_error(c4_repo):
    # The same broken file addressed as a whole (a bare path is a valid pytest
    # nodeid) exits 2 (interrupted by collection error) -> ERROR, never FAIL.
    res = run_c4(c4_repo, "pytest:tests/test_broken.py")
    assert res.verdict is Verdict.ERROR


@pytest.mark.slow
def test_no_tests_collected_is_fail_test_gone(c4_repo):
    write(c4_repo, "tests/test_none.py", "X = 1\n")  # exists, but collects nothing: exit 5
    res = run_c4(c4_repo, "pytest:tests/test_none.py")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "test_gone"


@pytest.mark.slow
def test_renamed_test_file_resolves_through_rename_map(c4_repo):
    git(c4_repo, "mv", MINI, "tests/test_suite.py")
    res = run_c4(
        c4_repo,
        f"pytest:{MINI}::test_green",
        rename_map={MINI: "tests/test_suite.py"},
    )
    assert res.verdict is Verdict.PASS  # a renamed test file is not 'gone'


@pytest.mark.slow
def test_timeout_is_error(c4_repo):
    res = run_c4(c4_repo, f"pytest:{MINI}::test_sleepy", timeout_s=1)
    assert res.verdict is Verdict.ERROR


def test_missing_pytest_module_is_error_pytest_missing(c4_repo, tmp_path, monkeypatch):
    """A PATH `python` whose environment lacks pytest exits 1 with empty stdout
    and runpy's "No module named pytest" on stderr. That is infrastructure, so
    it must map to ERROR(pytest_missing) — never FAIL, never a BROKEN claim."""
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text('#!/bin/sh\necho "$0: No module named pytest" >&2\nexit 1\n')
    fake_python.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin), prepend=os.pathsep)
    res = run_c4(c4_repo, f"pytest:{MINI}::test_green")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "pytest_missing"


# --- bad programs / containment ---------------------------------------------------


def test_malformed_programs_are_error_bad_program(c4_repo):
    for prog in (
        f"{MINI}::test_green",  # no 'pytest:' prefix
        "pytest:",  # empty nodeid
        "pytest:   ",  # whitespace nodeid
        f"unittest:{MINI}::test_green",  # wrong grammar prefix
    ):
        res = run_c4(c4_repo, prog)
        assert res.verdict is Verdict.ERROR, prog
        assert res.detail == "bad_program", prog


def test_nodeid_escaping_repo_is_error_bad_program(c4_repo):
    outside = c4_repo.parent / "test_outside.py"
    outside.write_text("def test_x():\n    assert True\n")
    for prog in ("pytest:../test_outside.py::test_x", f"pytest:{outside}::test_x"):
        res = run_c4(c4_repo, prog)
        assert res.verdict is Verdict.ERROR, prog
        assert res.detail == "bad_program", prog


# --- revalidation ordering: C4 is the most expensive checker ----------------------


def test_c3_fail_short_circuits_before_c4_spawns(c4_repo, monkeypatch):
    """_check_claim must run checkers cheapest-first (C1 < C3 < C5 < C4) and stop
    at the first FAIL: with C4 listed before a failing C3, pytest never spawns."""
    calls: list = []

    class _ProbeSubprocess:
        TimeoutExpired = subprocess.TimeoutExpired

        @staticmethod
        def run(*args, **kwargs):
            calls.append(args)
            raise OSError("probe: pytest must not spawn")

    monkeypatch.setattr(c4_mod, "subprocess", _ProbeSubprocess())
    claim = Claim(
        id="cl1",
        text="ordered claim",
        kind="behavior",
        load_bearing=True,
        checkers=(
            CheckerSpec(type="C4", program=f"pytest:{MINI}::test_green"),  # listed first
            CheckerSpec(type="C3", program="path:src/missing.py"),
        ),
    )
    state, detail, relocated = revalidate._check_claim(
        c4_repo, claim, {}, {}, False, ExecutionPolicy()
    )
    assert state == "BROKEN"
    assert detail == "C3: ref_missing"  # C3's FAIL (type-prefixed), not a C4 verdict
    assert not relocated
    assert calls == []  # C4 never ran: the cheap C3 FAIL short-circuited it


# --- seal-time behavior: born-verifiable applies to C4 too ------------------------


def _readset() -> ReadSet:
    return ReadSet(
        entries=(),
        produced_by=ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z"),
    )


def _c4_claim(nodeid: str) -> Claim:
    spec = CheckerSpec(type="C4", program=f"pytest:{nodeid}", watch=(MINI,))
    return Claim(
        id="c1", text="the mini suite passes", kind="behavior", load_bearing=True, checkers=(spec,)
    )


@pytest.mark.slow
def test_green_c4_claim_seals(c4_repo):
    w = seal_artifact(c4_repo, "docs/note.md", _readset(), [_c4_claim(f"{MINI}::test_green")])
    assert (c4_repo / "docs/note.md.warrant").is_file()
    assert w.claims[0].checkers[0].type == "C4"


@pytest.mark.slow
def test_c4_claim_without_watch_derives_watch_at_seal(c4_repo):
    """Regression: a C4 checker sealed with no explicit watch once got
    watch=[] silently (seal._derive_watch had no C4 branch), so the claim was
    never a revalidate candidate and stayed VERIFIED forever. The sealed
    sidecar must carry the nodeid's file part as the derived watch."""
    spec = CheckerSpec(type="C4", program=f"pytest:{MINI}::test_green")  # no watch
    claim = Claim(
        id="c1", text="the mini suite passes", kind="behavior", load_bearing=True, checkers=(spec,)
    )
    w = seal_artifact(c4_repo, "docs/note.md", _readset(), [claim])
    assert w.claims[0].checkers[0].watch == (MINI,)
    # and the binding is queryable: editing the test file makes the claim a candidate
    from dorian import store

    conn = store.connect(c4_repo)
    try:
        candidates = store.claims_for_paths(conn, [MINI])
    finally:
        conn.close()
    assert {(c["warrant_id"], c["claim_id"]) for c in candidates} == {(w.id, "c1")}


@pytest.mark.slow
def test_red_test_at_seal_is_failed_at_seal(c4_repo):
    with pytest.raises(SealError, match="FAILED_AT_SEAL: c1"):
        seal_artifact(c4_repo, "docs/note.md", _readset(), [_c4_claim(f"{MINI}::test_red")])
    assert not (c4_repo / "docs/note.md.warrant").exists()


@pytest.mark.slow
def test_c4_claim_round_trips_through_claims_io_and_cmd_seal(c4_repo, tmp_path):
    """Regression: CheckerType once omitted "C4", so claims_io rejected the only
    CLI route to seal a C4 claim (`dorian seal --claims`) with exit 2."""
    rs_path, claims_path = tmp_path / "rs.json", tmp_path / "claims.json"
    _readset().dump(rs_path)
    claims = [_c4_claim(f"{MINI}::test_green")]
    claims_io.save_claims(claims_path, claims)
    assert claims_io.load_claims(claims_path) == claims  # validation accepts C4
    args = cli.build_parser().parse_args(
        [
            "--repo",
            str(c4_repo),
            "seal",
            "docs/note.md",
            "--readset",
            str(rs_path),
            "--claims",
            str(claims_path),
        ]
    )
    assert commands.cmd_seal(args) == 0
    assert (c4_repo / "docs/note.md.warrant").is_file()
