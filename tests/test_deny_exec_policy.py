"""Execution-policy (deny-exec / deny-shell) regression tests.

The executable checker families (C4 pytest, C5 shell) run code on the machine
that invokes dorian; deny-exec is the opt-in that refuses to run them. The
invariants pinned here:

- classification is exact: ONLY C4 and C5 `shell:` are executable; C1, C3, and
  the typed C5 data forms are not;
- a blocked checker becomes Verdict.ERROR — never PASS (no silent green) and
  never FAIL (a refused checker has not proven the claim false);
- the gate short-circuits BEFORE the checker runs (pytest/shell never spawn);
- under deny-exec a blocked load-bearing claim does NOT seal (born-verifiable
  refuses ERROR), while non-executing C3 claims still seal normally;
- revalidate folds a blocked recheck to ERRORED, preserving trigger-vs-truth;
- deny-shell is the narrower setting (blocks C5 shell, still allows C4);
- the DORIAN_DENY_EXEC / DORIAN_DENY_SHELL env vars compose with the flags.

All cases are offline and local (no network, no real secrets).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import dorian.checkers.c4_test as c4_mod
from conftest import commit_all, git, write
from dorian import cli, revalidate
from dorian.capture.manual import parse_manual
from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import CheckerSpec, Claim, Warrant
from dorian.policy import ExecutionPolicy, executable_kind
from dorian.seal import seal_artifact

C4 = CheckerSpec(type="C4", program="pytest:tests/test_x.py::test_a")
C5_SHELL = CheckerSpec(type="C5", program="shell:echo hi")
C5_TYPED = CheckerSpec(type="C5", program="rowcount:data/lots.csv::>0")
C3 = CheckerSpec(type="C3", program="path:src/auth.py")

DENY_EXEC = ExecutionPolicy(allow_exec=False, allow_shell=False)
DENY_SHELL = ExecutionPolicy(allow_exec=True, allow_shell=False)
ALLOW = ExecutionPolicy()


def _checked(spec: CheckerSpec, policy: ExecutionPolicy, repo: Path):
    claim = Claim(id="c", text="x", kind="behavior", load_bearing=True, checkers=(spec,))
    return run_checker(CheckContext(repo=repo, claim=claim, policy=policy), 0)


# --- classification -----------------------------------------------------------


def test_executable_kind_classifies_only_c4_and_c5_shell() -> None:
    assert executable_kind(C4) == "pytest"
    assert executable_kind(C5_SHELL) == "shell"
    assert executable_kind(C5_TYPED) is None  # typed data forms read files, not exec
    assert executable_kind(C3) is None
    assert executable_kind(CheckerSpec(type="C1", program="L1-2")) is None


def test_block_reason_matrix() -> None:
    # deny-exec blocks both executable families
    assert "C4 pytest" in DENY_EXEC.block_reason(C4)
    assert "C5 shell" in DENY_EXEC.block_reason(C5_SHELL)
    # deny-shell blocks shell only, leaves pytest available
    assert DENY_SHELL.block_reason(C4) is None
    assert "deny-shell" in DENY_SHELL.block_reason(C5_SHELL)
    # default policy blocks nothing
    assert ALLOW.block_reason(C4) is None
    assert ALLOW.block_reason(C5_SHELL) is None
    # non-executing checkers are never blocked, even under deny-exec
    assert DENY_EXEC.block_reason(C3) is None
    assert DENY_EXEC.block_reason(C5_TYPED) is None


def test_from_flags_and_env_composition(monkeypatch) -> None:
    monkeypatch.delenv("DORIAN_DENY_EXEC", raising=False)
    monkeypatch.delenv("DORIAN_DENY_SHELL", raising=False)
    # no flags, no env -> allow all (today's behavior)
    assert ExecutionPolicy.from_flags_and_env() == ExecutionPolicy(True, True)
    # deny-exec implies deny-shell
    assert ExecutionPolicy.from_flags_and_env(deny_exec=True) == ExecutionPolicy(False, False)
    # deny-shell alone keeps exec on
    assert ExecutionPolicy.from_flags_and_env(deny_shell=True) == ExecutionPolicy(True, False)
    # env fallback denies even without the flag
    monkeypatch.setenv("DORIAN_DENY_EXEC", "1")
    assert ExecutionPolicy.from_flags_and_env() == ExecutionPolicy(False, False)
    monkeypatch.setenv("DORIAN_DENY_EXEC", "0")  # falsey is a no-op
    monkeypatch.setenv("DORIAN_DENY_SHELL", "true")
    assert ExecutionPolicy.from_flags_and_env() == ExecutionPolicy(True, False)
    # env-deny-exec escalates a deny_shell flag to full deny (pins the OR-compose:
    # a regression dropping the env term would fail here, not pass silently)
    monkeypatch.setenv("DORIAN_DENY_EXEC", "yes")
    monkeypatch.delenv("DORIAN_DENY_SHELL", raising=False)
    assert ExecutionPolicy.from_flags_and_env(deny_shell=True) == ExecutionPolicy(False, False)


# --- run_checker gate: blocked is ERROR, and nothing spawns -------------------


def test_run_checker_blocks_c4_under_deny_exec(tmp_path: Path) -> None:
    res = _checked(C4, DENY_EXEC, tmp_path)
    assert res.verdict is Verdict.ERROR  # never PASS, never FAIL
    assert "execution policy" in res.detail and "C4 pytest" in res.detail


def test_run_checker_blocks_c5_shell_under_deny_exec(tmp_path: Path) -> None:
    res = _checked(C5_SHELL, DENY_EXEC, tmp_path)
    assert res.verdict is Verdict.ERROR
    assert "execution policy" in res.detail and "C5 shell" in res.detail


def test_deny_exec_blocks_c4_before_spawn_deny_shell_lets_it_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    """Two promises, proven with a subprocess probe:
    - deny-exec blocks C4 BEFORE the checker runs (the probe is NEVER called: no spawn);
    - deny-shell does NOT pre-empt C4 (only C5 shell), so it dispatches and the probe IS hit."""
    calls: list = []

    class _Probe:
        TimeoutExpired = subprocess.TimeoutExpired

        @staticmethod
        def run(*args, **kwargs):
            calls.append(args)
            raise OSError("probe: pytest must not spawn under deny-exec")

    monkeypatch.setattr(c4_mod, "subprocess", _Probe())

    # deny-exec: gate short-circuits before dispatch -> ERROR, and pytest NEVER spawns
    res = _checked(C4, DENY_EXEC, tmp_path)
    assert res.verdict is Verdict.ERROR and "execution policy" in res.detail
    assert calls == [], "deny-exec must block C4 before it spawns a subprocess"

    # deny-shell: C4 is not pre-empted, it dispatches and the probe records the spawn attempt
    calls.clear()
    _checked(C4, DENY_SHELL, tmp_path)
    assert calls, "deny-shell blocks only C5 shell; C4 must still dispatch to its checker"

    # C5 shell is blocked under deny-shell -> ERROR (the narrow setting still gates shell)
    assert _checked(C5_SHELL, DENY_SHELL, tmp_path).verdict is Verdict.ERROR


def test_run_checker_allows_non_executing_under_deny_exec(fixture_repo: Path) -> None:
    assert _checked(C3, DENY_EXEC, fixture_repo).verdict is Verdict.PASS
    assert _checked(C5_TYPED, DENY_EXEC, fixture_repo).verdict is Verdict.PASS


# --- seal-time: blocked load-bearing claim does not seal ----------------------


def _repo_with_test(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "tests/test_x.py", "def test_a():\n    assert True\n")
    write(repo, "note.md", "# change\n\nThe test_a guard passes.\n")
    write(
        repo,
        "claims.json",
        json.dumps(
            {
                "claims": [
                    {
                        "id": "guard",
                        "text": "test_a passes.",
                        "kind": "behavior",
                        "load_bearing": True,
                        "checkers": [{"type": "C4", "program": "pytest:tests/test_x.py::test_a"}],
                    }
                ]
            }
        ),
    )
    commit_all(repo, "test + note + claims")
    return repo


def test_verify_deny_exec_refuses_c4_claim_and_writes_no_sidecar(tmp_path: Path) -> None:
    repo = _repo_with_test(tmp_path)
    rc = cli.main(
        [
            "--repo",
            str(repo),
            "verify",
            "note.md",
            "--claims",
            str(repo / "claims.json"),
            "--deny-exec",
        ]
    )
    assert rc == cli.EXIT_REVOKED  # born-verifiable refuses an ERROR at seal (exit 4)
    assert not (repo / "note.md.warrant").exists()  # atomic: no sidecar on refusal


def test_verify_deny_exec_still_seals_non_executing_c3(fixture_repo: Path) -> None:
    """deny-exec must not break the normal (non-executing) workflow."""
    claims = {
        "claims": [
            {
                "id": "vt",
                "text": "verify_token is defined.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            }
        ]
    }
    cp = fixture_repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    rc = cli.main(
        [
            "--repo",
            str(fixture_repo),
            "verify",
            "docs/design.md",
            "--claims",
            str(cp),
            "--deny-exec",
        ]
    )
    assert rc == cli.EXIT_OK
    assert (fixture_repo / "docs/design.md.warrant").is_file()


# --- revalidate: a blocked recheck folds to ERRORED, never PASS/BROKEN --------


def test_revalidate_check_claim_blocks_c4_as_errored(tmp_path: Path) -> None:
    claim = Claim(id="g", text="x", kind="behavior", load_bearing=True, checkers=(C4,))
    state, detail, relocated = revalidate._check_claim(tmp_path, claim, {}, {}, False, DENY_EXEC)
    assert state == "ERRORED"  # not VERIFIED (silent pass) and not BROKEN (false)
    assert "execution policy" in detail
    assert not relocated


# --- rebind is an executable surface too: it must honor deny-exec --------------


def test_rebind_honors_deny_exec_and_refuses_to_reexecute(fixture_repo: Path, monkeypatch) -> None:
    """Regression: `dorian rebind` RE-RUNS every checker to re-seal, so it must
    honor deny-exec exactly like seal/verify. A warrant carrying a C5 shell claim
    whose text also names an unwatched symbol (so rebind has a new binding to add
    and actually proceeds to re-seal) must, under DORIAN_DENY_EXEC=1, refuse the
    re-seal (exit 4) and leave the old sidecar id untouched — never silently
    re-execute the shell command."""
    rs = parse_manual(["src/config.py"], fixture_repo)
    claim = Claim(
        id="sh",
        # mentions verify_token (defined only in src/auth.py, NOT in this watch),
        # so rebind binds src/auth.py and proceeds to re-seal
        text="verify_token still passes its guard.",
        kind="behavior",
        load_bearing=True,
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C5", program="shell:true", watch=("src/config.py",)),),
    )
    old = seal_artifact(fixture_repo, "docs/design.md", rs, [claim])  # shell:true passes -> sealed

    monkeypatch.setenv("DORIAN_DENY_EXEC", "1")
    rc = cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"])
    # blocked shell -> ERROR -> SealError(ERRORED_AT_SEAL) -> rebind refuses (exit 4)
    assert rc == cli.EXIT_REVOKED, "rebind must refuse to re-execute a blocked checker"
    # atomic no-write: the original warrant id is unchanged (no re-seal happened)
    assert Warrant.load(fixture_repo / "docs/design.md.warrant").id == old.id
