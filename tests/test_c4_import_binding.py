"""C4 import-aware dependency binding: a C4 ``pytest:`` checker proves behavior
WHEN IT RUNS, but its sealed watch is only the nodeid's test file. If the
implementation the test exercises changes and the claim text names no uniquely
indexed symbol/config key, revalidation can skip the claim entirely even though
an adequate behavior checker exists — a re-check TRIGGER gap (silent skip), not a
truth gap.

``test_deps.python_import_dependencies`` statically resolves the repo-local Python
files a test file imports (stdlib ``ast`` only — no import execution, no sys.path
mutation, no package introspection); ``verify``/``rebind`` add those to the C4
claim's watch + read-set so a source edit re-runs the existing C4 checker. The
checker still decides truth: a file change is a trigger, never a BROKEN.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from conftest import commit_all, write
from dorian import claims_io, cli, gitio
from dorian.model import CheckerSpec, Claim, Warrant
from dorian.revalidate import revalidate

# --- unit coverage for the static import resolver -------------------------------------


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitio_init(repo)
    return repo


def gitio_init(repo: Path) -> None:
    from conftest import git

    git(repo, "init", "-q", "-b", "main")


def test_resolves_repo_local_absolute_imports(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/auth.py", "def verify_token(t):\n    return bool(t)\n")
    write(repo, "src/rate_limit.py", "limiter = object()\n")
    write(
        repo,
        "tests/test_auth.py",
        "import os\n"
        "from src.auth import verify_token\n"
        "from src.rate_limit import limiter\n"
        "import pytest\n\n"
        "def test_x():\n    assert verify_token('x')\n",
    )
    commit_all(repo, "init")
    deps = test_deps.python_import_dependencies(repo, "tests/test_auth.py")
    # repo-local imports resolve; stdlib (os) and third-party (pytest) are skipped
    assert deps == ("src/auth.py", "src/rate_limit.py")


def test_resolves_plain_module_import(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/config.py", "TIMEOUT = 30\n")
    write(repo, "tests/test_cfg.py", "import src.config\n\ndef test_x():\n    pass\n")
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_cfg.py") == ("src/config.py",)


def test_resolves_package_init(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "pkg/__init__.py", "VALUE = 1\n")
    write(repo, "tests/test_pkg.py", "import pkg\n\ndef test_x():\n    pass\n")
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_pkg.py") == ("pkg/__init__.py",)


def test_ambiguous_module_tail_is_skipped(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    # `auth` as a module tail matches BOTH files -> the definer is unknowable, skip it
    # (a wrong watch is a false-BROKEN risk; mirrors symbol_index ambiguity handling)
    write(repo, "auth.py", "X = 1\n")
    write(repo, "src/auth.py", "Y = 2\n")
    write(repo, "tests/test_a.py", "import auth\n\ndef test_x():\n    pass\n")
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_a.py") == ()


def test_relative_import_within_package(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "pkg/__init__.py", "")
    write(repo, "pkg/impl.py", "def f():\n    return 1\n")
    write(repo, "pkg/test_impl.py", "from .impl import f\n\ndef test_x():\n    assert f()\n")
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "pkg/test_impl.py") == ("pkg/impl.py",)


def test_relative_import_above_root_is_skipped(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "pkg/test_x.py", "from ... import nope\n\ndef test_x():\n    pass\n")
    commit_all(repo, "init")
    # too many leading dots to resolve inside the repo: skip, never crash
    assert test_deps.python_import_dependencies(repo, "pkg/test_x.py") == ()


def test_third_party_and_stdlib_never_resolve(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(
        repo,
        "tests/test_x.py",
        "import os\nimport pytest\nfrom collections import OrderedDict\n",
    )
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_x.py") == ()


def test_syntax_error_file_is_non_fatal(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "tests/test_x.py", "def oops(:\n    pass\n")  # unparseable
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_x.py") == ()


def test_oversized_file_is_skipped(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/m.py", "def f():\n    return 1\n")
    big = "from src.m import f\n" + ("# pad\n" * 200_000)  # > 1 MiB
    write(repo, "tests/test_big.py", big)
    commit_all(repo, "init")
    assert (repo / "tests/test_big.py").stat().st_size > (1 << 20)
    assert test_deps.python_import_dependencies(repo, "tests/test_big.py") == ()


def test_non_git_repo_yields_no_deps(tmp_path: Path) -> None:
    from dorian import test_deps

    (tmp_path / "tests").mkdir()
    (tmp_path / "src.py").write_text("X = 1\n")
    (tmp_path / "tests" / "test_x.py").write_text("import src\n")
    assert test_deps.python_import_dependencies(tmp_path, "tests/test_x.py") == ()


def test_untracked_test_file_yields_no_deps(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/m.py", "def f():\n    return 1\n")
    commit_all(repo, "init")
    write(repo, "tests/test_untracked.py", "from src.m import f\n")  # never git-added
    assert test_deps.python_import_dependencies(repo, "tests/test_untracked.py") == ()


def test_self_import_excluded_and_deterministic(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/a.py", "X = 1\n")
    write(repo, "src/b.py", "Y = 2\n")
    write(
        repo,
        "tests/test_ab.py",
        "from src.b import Y\nfrom src.a import X\n\ndef test_x():\n    pass\n",
    )
    commit_all(repo, "init")
    a = test_deps.python_import_dependencies(repo, "tests/test_ab.py")
    b = test_deps.python_import_dependencies(repo, "tests/test_ab.py")
    assert a == b == ("src/a.py", "src/b.py")  # sorted, deduped, deterministic
    assert "tests/test_ab.py" not in a  # never lists itself


def test_stdlib_name_collision_is_not_bound(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    # a repo file shares a basename with a stdlib module. A stdlib `import json` must NOT
    # bind it: the resolver consults the interpreter's stdlib module-name table, so a
    # same-named repo file is never a false re-check trigger for a stdlib import (which is
    # what the bare path-tail match would otherwise do).
    write(repo, "pkg/json.py", "X = 1\n")
    write(repo, "tests/test_x.py", "import json\n\ndef test_x():\n    pass\n")
    commit_all(repo, "init")
    assert test_deps.python_import_dependencies(repo, "tests/test_x.py") == ()


def test_symlinked_test_file_is_not_followed_out_of_repo(tmp_path: Path) -> None:
    from conftest import git
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/m.py", "def f():\n    return 1\n")
    # an out-of-repo source the symlink points at; following it would ast.parse bytes
    # OUTSIDE the tracked repo. The resolver must skip symlinks, not follow them.
    outside = tmp_path / "outside.py"
    outside.write_text("from src.m import f\n")
    link = repo / "tests" / "test_link.py"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, link)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "track a symlinked test file")
    assert "tests/test_link.py" in gitio.ls_files(repo)  # git tracks it (mode 120000)
    # tracked, but a symlink to an out-of-repo file: skipped, so nothing is read or bound
    assert test_deps.python_import_dependencies(repo, "tests/test_link.py") == ()


def test_c4_dependency_watch_paths_maps_claims(tmp_path: Path) -> None:
    from dorian import test_deps

    repo = _repo(tmp_path)
    write(repo, "src/auth.py", "def verify_token(t):\n    return bool(t)\n")
    write(
        repo,
        "tests/test_auth.py",
        "from src.auth import verify_token\n\ndef test_x():\n    pass\n",
    )
    commit_all(repo, "init")
    claim = Claim(
        id="c1",
        text="login works",
        kind="behavior",
        load_bearing=True,
        checkers=(CheckerSpec(type="C4", program="pytest:tests/test_auth.py::test_x"),),
    )
    other = Claim(
        id="c2",
        text="no c4 here",
        kind="reference",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="path:src/auth.py"),),
    )
    out = test_deps.c4_dependency_watch_paths(repo, [claim, other])
    assert out == {"c1": ("src/auth.py",)}  # only the C4 claim, only the imported impl


def test_merge_watch_maps_unions_per_claim(tmp_path: Path) -> None:
    from dorian import test_deps

    a = {"c1": ("x.py",), "c2": ("y.py",)}
    b = {"c1": ("z.py",), "c3": ("w.py",)}
    assert test_deps.merge_watch_maps(a, b) == {
        "c1": ("x.py", "z.py"),
        "c2": ("y.py",),
        "c3": ("w.py",),
    }


# --- integration: verify / revalidate / rebind / bindings / scope / deny-exec ---------
#
# The gap this patch closes: a C4-backed BEHAVIOR claim whose text names NO uniquely
# indexed symbol, so the symbol index binds nothing. Without C4 import binding the
# sealed watch is only the test file, so an edit to the implementation the test
# imports is never selected for revalidation — the claim stays trusted on stale
# confidence. With it, the imported impl file is watched, so the edit re-runs the
# existing C4 checker and the checker decides truth.

AUTH_SRC = "def verify_token(token):\n    return token == 'good'\n"

TEST_LOGIN = (
    "from src.auth import verify_token\n\n\n"
    "def test_login_rejects_invalid_token():\n"
    "    assert verify_token('good') is True\n"
    "    assert verify_token('bad') is False\n"
)

# vague behavior claim: the text names no snake_case/CamelCase/backtick/path token, so
# symbol_index binds nothing — the ONLY source of src/auth.py in the watch is the C4
# test's `from src.auth import verify_token` (pinned in the test below).
C4_BEHAVIOR_CLAIM = Claim(
    id="login-behavior",
    text="Login rejects invalid tokens.",
    kind="behavior",
    load_bearing=True,
    checkers=(
        CheckerSpec(
            type="C4",
            program="pytest:tests/test_login.py::test_login_rejects_invalid_token",
        ),
    ),
)


@pytest.fixture
def c4_import_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path)
    write(repo, "docs/design.md", "# Design\n\nLogin rejects invalid tokens.\n")
    write(repo, "src/__init__.py", "")  # `from src.auth import ...` resolves under `python -m`
    write(repo, "src/auth.py", AUTH_SRC)
    write(repo, "tests/test_login.py", TEST_LOGIN)
    commit_all(repo, "init c4 import scenario")
    return repo


@pytest.fixture
def interpreter_on_path(monkeypatch):
    # the C4 checker spawns bare `python -m pytest`; ensure it resolves an interpreter
    # that has pytest regardless of how this suite was invoked (mirrors test_c4.py)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent), prepend=os.pathsep)


def _verify(repo: Path, claims: list[Claim], *extra: str) -> int:
    return cli.main(
        ["--repo", str(repo), "verify", "docs/design.md", "--claims", _saved(repo, claims), *extra]
    )


def _warrant(repo: Path) -> Warrant:
    return Warrant.load(repo / "docs/design.md.warrant")


@pytest.mark.slow
def test_verify_widens_watch_and_captures_imported_impl(
    c4_import_repo: Path, interpreter_on_path
) -> None:
    from dorian import symbol_index, test_deps

    repo = c4_import_repo
    # isolate the contribution: the claim text binds NO symbol-definer / config watch
    assert symbol_index.claim_watch_paths(repo, [C4_BEHAVIOR_CLAIM]) == {}
    assert test_deps.c4_dependency_watch_paths(repo, [C4_BEHAVIOR_CLAIM]) == {
        "login-behavior": ("src/auth.py",)
    }

    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0  # born verifiable: the pytest passes now
    claim = _warrant(repo).claims[0]
    # the C4 checker named only the test file; import binding added src/auth.py to both
    # the sealed watch and the auto-captured (hashed, scope-linted) read-set
    assert claim.checkers[0].watch == ("tests/test_login.py", "src/auth.py")
    assert "src/auth.py" in {e.uri for e in _warrant(repo).read_set}


@pytest.mark.slow
def test_impl_change_makes_claim_broken(c4_import_repo: Path, interpreter_on_path) -> None:
    repo = c4_import_repo
    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0
    base = gitio.head_ref(repo)
    # break the behavior the test asserts; the test file and claim text are untouched, so
    # WITHOUT import binding this drift is silently skipped (the old test-file-only watch)
    write(repo, "src/auth.py", "def verify_token(token):\n    return token == 'nope'\n")

    res = revalidate(repo, since=base)
    assert res.candidates >= 1  # was 0 before the fix: the claim was never re-checked
    assert "login-behavior" in {cid for _, cid, _ in res.broken}  # a real CATCH
    assert res.exit_code == 4  # load-bearing claim broke -> warrant REVOKED


@pytest.mark.slow
def test_benign_impl_change_re_runs_but_does_not_alarm(
    c4_import_repo: Path, interpreter_on_path
) -> None:
    repo = c4_import_repo
    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0
    base = gitio.head_ref(repo)
    # a behavior-preserving edit: the test still passes. The widened watch selects the
    # claim (the imported file changed) but the verdict comes from the test -> PASS, not
    # BROKEN. File drift is a re-check TRIGGER, never proof a claim is false.
    write(
        repo,
        "src/auth.py",
        "def verify_token(token):\n    # tidy up\n    return token == 'good'\n",
    )

    res = revalidate(repo, since=base)
    assert res.candidates >= 1
    assert "login-behavior" in {cid for _, cid, _ in res.passed}
    assert "login-behavior" not in {cid for _, cid, _ in res.broken}
    assert res.exit_code == 0


@pytest.mark.slow
def test_deny_exec_makes_selected_claim_errored_not_broken(
    c4_import_repo: Path, interpreter_on_path
) -> None:
    from dorian.policy import ExecutionPolicy

    repo = c4_import_repo
    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0
    base = gitio.head_ref(repo)
    # would fail the test if executed:
    write(repo, "src/auth.py", "def verify_token(token):\n    return token == 'nope'\n")

    res = revalidate(repo, since=base, policy=ExecutionPolicy(allow_exec=False))
    assert res.candidates >= 1  # the wider watch still SELECTS the claim
    assert "login-behavior" in {cid for _, cid, _ in res.errored}  # blocked C4 -> ERRORED
    assert "login-behavior" not in {cid for _, cid, _ in res.broken}  # never BROKEN under deny-exec
    assert res.exit_code == 5  # UNKNOWN (fail-closed), not REVOKED and not OK


def test_scope_lint_sees_import_derived_path(c4_import_repo: Path) -> None:
    # the import-derived impl file is captured into the read-set, so it is scope-linted
    # like any other entry: a restricted impl file refuses the seal (exit 6) unless allowed.
    # No interpreter fixture needed: scope lint runs BEFORE any checker.
    repo = c4_import_repo
    write(repo, "pyproject.toml", '[tool.dorian.scopes]\nrestricted = ["src/auth.py"]\n')
    commit_all(repo, "restrict src/auth.py")
    cp = _saved(repo, [C4_BEHAVIOR_CLAIM])
    base = ["--repo", str(repo), "verify", "docs/design.md", "--claims", cp]
    assert cli.main(base) == 6  # EXIT_SCOPE: import-derived src/auth.py is restricted
    assert not (repo / "docs/design.md.warrant").exists()
    assert cli.main([*base, "--allow-restricted"]) == 0  # explicit allowance seals


@pytest.mark.slow
def test_bindings_does_not_flag_import_exercised_watch_as_trigger_only(
    c4_import_repo: Path, capsys
) -> None:
    import json

    repo = c4_import_repo
    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0
    capsys.readouterr()  # flush verify's stdout before reading the bindings JSON
    assert cli.main(["--repo", str(repo), "--json", "bindings", "docs/design.md"]) == 0
    diags = json.loads(capsys.readouterr().out)["claims"]
    claim_diag = next(c for c in diags if c["claim_id"] == "login-behavior")
    # PIN THE WIDENING FIRST: import binding must have added src/auth.py to the watch.
    # Without this, the test is vacuous — a narrow test-file-only watch is trivially
    # checker-exercised, so 'trigger-only-symbol' would be absent even if the feature
    # were reverted. The flag assertion only means something once widening is proven.
    assert "src/auth.py" in claim_diag["watch"]
    # the C4 test IMPORTS src/auth.py, so when it runs it exercises that file: the widened
    # watch is checker-exercised, NOT trigger-only. Flagging it would (a) be wrong and (b)
    # trip --binding-gate=fail on a good behavior claim.
    assert "trigger-only-symbol" not in claim_diag["flags"]


@pytest.mark.slow
def test_binding_gate_fail_still_seals_good_c4_behavior_claim(
    c4_import_repo: Path,
) -> None:
    # the accidental-gate guard: --binding-gate=fail must NOT refuse a load-bearing C4
    # claim merely because import binding widened its watch (it would, if the import-deps
    # were treated as trigger-only). It seals (exit 0).
    repo = c4_import_repo
    cp = _saved(repo, [C4_BEHAVIOR_CLAIM])
    rc = cli.main(
        ["--repo", str(repo), "verify", "docs/design.md", "--claims", cp, "--binding-gate", "fail"]
    )
    assert rc == 0
    # PIN THE WIDENING: prove the gate tolerated an IMPORT-WIDENED watch specifically (not
    # just an un-widened claim). The sealed C4 watch must contain the import-derived
    # src/auth.py — else rc==0 would hold even with the feature reverted (vacuous pass).
    assert "src/auth.py" in _warrant(repo).claims[0].checkers[0].watch


def test_bind_suggest_surfaces_test_deps(c4_import_repo: Path, capsys) -> None:
    import json

    repo = c4_import_repo
    cp = _saved(repo, [C4_BEHAVIOR_CLAIM])
    assert cli.main(["--repo", str(repo), "--json", "bind-suggest", "--claims", cp]) == 0
    sugg = json.loads(capsys.readouterr().out)["suggestions"]
    s = next(x for x in sugg if x["claim_id"] == "login-behavior")
    assert s["bind_test_deps"] == ["src/auth.py"]  # import-derived, content-free (path only)


@pytest.mark.slow
def test_rebind_upgrades_old_c4_warrant_watch(c4_import_repo: Path, interpreter_on_path) -> None:
    from dorian.capture.manual import parse_manual
    from dorian.seal import seal_artifact

    repo = c4_import_repo
    # simulate a PRE-import-binding warrant: seal with extra_watch=None so the imported
    # impl (src/auth.py) is NOT watched and a change there would be silently skipped.
    old = seal_artifact(
        repo, "docs/design.md", parse_manual(["tests/test_login.py"], repo), [C4_BEHAVIOR_CLAIM]
    )
    assert old.claims[0].checkers[0].watch == ("tests/test_login.py",)  # narrow (pre-fix)

    assert cli.main(["--repo", str(repo), "rebind", "docs/design.md"]) == 0
    new = _warrant(repo)
    assert new.claims[0].checkers[0].watch == ("tests/test_login.py", "src/auth.py")  # widened
    assert new.supersedes == old.id
    assert "src/auth.py" in {e.uri for e in new.read_set}


@pytest.mark.slow
def test_rebind_refuses_to_launder_a_since_broken_c4_claim(
    c4_import_repo: Path, interpreter_on_path
) -> None:
    from dorian.capture.manual import parse_manual
    from dorian.seal import seal_artifact

    repo = c4_import_repo
    # a PRE-import-binding warrant: narrow test-file-only watch (src/auth.py not watched).
    old = seal_artifact(
        repo, "docs/design.md", parse_manual(["tests/test_login.py"], repo), [C4_BEHAVIOR_CLAIM]
    )
    assert old.claims[0].checkers[0].watch == ("tests/test_login.py",)
    # break the behavior the C4 test asserts. rebind re-runs every checker (born-verifiable),
    # so the now-FAILING pytest must REFUSE the re-seal (exit 4) rather than launder a false
    # claim into a fresh trusted sidecar with a widened watch.
    write(repo, "src/auth.py", "def verify_token(token):\n    return token == 'nope'\n")
    assert cli.main(["--repo", str(repo), "rebind", "docs/design.md"]) == 4
    # nothing written: the old sidecar (and its id and narrow watch) is left intact
    assert _warrant(repo).id == old.id
    assert _warrant(repo).claims[0].checkers[0].watch == ("tests/test_login.py",)


@pytest.mark.slow
def test_trusted_base_mode_runs_base_spec_with_widened_watch(
    c4_import_repo: Path, interpreter_on_path
) -> None:
    # checker-source=base: the wider watch (baked into the head sidecar) still SELECTS the
    # claim; base mode resolves the (here identical) checker spec from the base ref and runs
    # it against head sources. A broken impl on head -> BROKEN, exit 4. Import binding does
    # not weaken trusted-base fail-closed semantics.
    repo = c4_import_repo
    assert _verify(repo, [C4_BEHAVIOR_CLAIM]) == 0
    commit_all(repo, "commit warrant so it exists on the base ref")
    base = gitio.head_ref(repo)
    write(repo, "src/auth.py", "def verify_token(token):\n    return token == 'nope'\n")

    res = revalidate(repo, since=base, checker_source="base")
    assert "login-behavior" in {cid for _, cid, _ in res.broken}
    assert res.exit_code == 4


def _saved(repo: Path, claims: list[Claim]) -> str:
    claims_io.save_claims(repo / "claims.json", claims)
    return str(repo / "claims.json")
