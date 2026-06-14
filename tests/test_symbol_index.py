"""The binding fix: a Python symbol->defining-file index that widens a claim's
checker watch set with the file that DEFINES a symbol the claim mentions, even
when the claim text never names that file.

This closes the *silent-skip* class (NEXT_ALGORITHMIC_BETS.md #1): a claim about
a symbol could watch only the file its checker named, so a change to the file
that actually DEFINES the symbol never triggered revalidation at all. The widened
watch makes such a change re-check the claim (Test B) — but it widens the re-check
TRIGGER, not the checks: the verdict still comes from the claim's own checkers, so
a checker that exercises the symbol breaks while a checker on an unrelated file
re-runs and PASSES (Test B pins exactly this). Conservative by construction — only
identifier-shaped tokens that resolve to EXACTLY ONE defining file are bound, so an
ambiguous symbol (Test C) and free-form prose add nothing; unreadable / invalid /
pathological Python never breaks the index (Test D + pathological-AST test).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from conftest import AUTH_PY, ROUTES_PY, commit_all, write
from dorian import claims_io, cli, gitio, store, symbol_index
from dorian.model import CheckerSpec, Claim, Warrant
from dorian.revalidate import revalidate

# a claim whose TEXT mentions the symbol `verify_token` (defined in src/auth.py
# by the fixture) but whose checker watches a DIFFERENT file (src/routes.py). The
# checker holds at seal time, so the warrant is born verifiable.
LOGIN_CLAIM = Claim(
    id="login-gate",
    text="Login is gated by verify_token.",
    kind="reference",
    load_bearing=False,
    checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
)


def _verify(repo: Path, claims: list[Claim]) -> int:
    claims_io.save_claims(repo / "claims.json", claims)
    return cli.main(
        ["--repo", str(repo), "verify", "docs/design.md", "--claims", str(repo / "claims.json")]
    )


def _warrant(repo: Path) -> Warrant:
    return Warrant.load(repo / "docs/design.md.warrant")


# --- Test A: watch the definer even when the claim text never names the file ----------


def test_A_verify_watches_symbol_definer_and_captures_it(fixture_repo: Path) -> None:
    assert _verify(fixture_repo, [LOGIN_CLAIM]) == 0
    claim = _warrant(fixture_repo).claims[0]
    # the checker named routes.py; the symbol index added auth.py (verify_token's
    # defining file) even though the claim text never said "src/auth.py"
    assert claim.checkers[0].watch == ("src/routes.py", "src/auth.py")
    # and the added definer is in the auto-captured read-set, so scope checks and
    # sidecar evidence stay honest about what the seal actually depended on
    assert "src/auth.py" in {e.uri for e in _warrant(fixture_repo).read_set}


# --- Test B: a change to the defining file is then caught by revalidation --------------


def test_B_definer_change_makes_claim_a_candidate(fixture_repo: Path) -> None:
    assert _verify(fixture_repo, [LOGIN_CLAIM]) == 0
    base = gitio.head_ref(fixture_repo)
    # rename the symbol inside its defining file; the claim and its checker file
    # (routes.py) are untouched, so without the watch expansion this drift is silent
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("verify_token", "renamed_token"))

    res = revalidate(fixture_repo, since=base)
    assert res.candidates >= 1  # was 0 before the fix: the claim was never re-checked at all
    rechecked = {
        cid for grp in (res.passed, res.broken, res.relocated, res.errored) for _, cid, _ in grp
    }
    assert "login-gate" in rechecked  # the exact claim was selected and re-checked

    # HONEST PIN (adversarial-review finding): the widened watch makes the claim a
    # CANDIDATE when its symbol's definer changes — but the verdict still comes from
    # the claim's OWN checker, which here inspects routes.py (UNCHANGED), so it
    # re-runs and PASSES. The fix closes the silent-skip gap (the claim is now
    # re-examined); it only flips to BROKEN when a checker exercises the symbol.
    assert "login-gate" in {cid for _, cid, _ in res.passed}
    assert "login-gate" not in {cid for _, cid, _ in res.broken}


# --- Test C: an ambiguous symbol stays low-FP (no auto-watch) --------------------------


def test_C_ambiguous_symbol_is_not_auto_watched(fixture_repo: Path) -> None:
    # the same symbol name now lives in two files -> the definer is unknowable, so
    # the conservative index must add neither (a wrong watch is a false BROKEN risk)
    write(fixture_repo, "src/dup.py", "def verify_token(token):\n    return bool(token)\n")
    commit_all(fixture_repo, "add a second verify_token definition")

    index = symbol_index.python_symbol_definers(fixture_repo)
    assert set(index["verify_token"]) == {"src/auth.py", "src/dup.py"}  # ambiguous
    assert symbol_index.claim_symbol_watch_paths(fixture_repo, [LOGIN_CLAIM]) == {}

    assert _verify(fixture_repo, [LOGIN_CLAIM]) == 0
    claim = _warrant(fixture_repo).claims[0]
    assert claim.checkers[0].watch == ("src/routes.py",)  # unchanged: no auth.py, no dup.py
    assert {e.uri for e in _warrant(fixture_repo).read_set} == {"src/routes.py"}


# --- Test D: a syntactically invalid Python file never breaks the index ----------------


def test_D_bad_python_is_non_fatal(fixture_repo: Path) -> None:
    write(fixture_repo, "src/broken.py", "def oops(:\n    pass\n")  # unparseable
    commit_all(fixture_repo, "add a syntactically broken python file")

    # the index skips broken.py and still indexes the valid files
    index = symbol_index.python_symbol_definers(fixture_repo)
    assert index["verify_token"] == ("src/auth.py",)

    # verify must succeed (exit 0) and still bind the definer
    assert _verify(fixture_repo, [LOGIN_CLAIM]) == 0
    assert "src/auth.py" in _warrant(fixture_repo).claims[0].checkers[0].watch


# --- unit coverage: the index shape (functions, async, classes; sorted; dedup) ---------


def test_index_collects_functions_async_and_classes(fixture_repo: Path) -> None:
    write(
        fixture_repo,
        "src/shapes.py",
        "class TokenStore:\n"
        "    def get(self):\n"
        "        return 1\n"
        "\n"
        "async def fetch_token():\n"
        "    return 2\n",
    )
    commit_all(fixture_repo, "add a class + async def")
    index = symbol_index.python_symbol_definers(fixture_repo)
    assert index["TokenStore"] == ("src/shapes.py",)  # class
    assert index["fetch_token"] == ("src/shapes.py",)  # async function
    assert index["verify_token"] == ("src/auth.py",)  # plain function, still there


def test_claim_watch_paths_ignores_prose_and_unknown_identifiers(fixture_repo: Path) -> None:
    # free-form English words (no underscore / no internal caps) are never tokens,
    # and a snake_case identifier with no definition in the repo resolves to nothing
    claim = Claim(
        id="prose",
        text="The login flow is gated and uses no_such_symbol somewhere.",
        kind="fact",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    assert symbol_index.claim_symbol_watch_paths(fixture_repo, [claim]) == {}


def test_index_is_deterministic_across_repeats(fixture_repo: Path) -> None:
    a = symbol_index.python_symbol_definers(fixture_repo)
    b = symbol_index.python_symbol_definers(fixture_repo)
    assert a == b
    assert all(list(v) == sorted(v) for v in a.values())  # files sorted within each symbol


def test_verify_path_unaffected_when_no_symbol_mentioned(fixture_repo: Path) -> None:
    # a claim with no identifier token must seal exactly as before (no extra watch,
    # no extra read-set entry) — the expansion is strictly opt-in on real symbols
    claim = Claim(
        id="rows",
        text="The lots dataset has 4 rows.",
        kind="quantity",
        load_bearing=False,
        checkers=(CheckerSpec(type="C5", program="rowcount:data/lots.csv::== 4"),),
    )
    assert _verify(fixture_repo, [claim]) == 0
    w = _warrant(fixture_repo)
    assert w.claims[0].checkers[0].watch == ("data/lots.csv",)
    assert {e.uri for e in w.read_set} == {"data/lots.csv"}
    store.connect(fixture_repo).close()


# --- regressions from the adversarial review (NON-FATAL + scope honesty) ---------------


def _raiser(exc):
    def _raise(*_args, **_kwargs):
        raise exc("simulated pathological AST")

    return _raise


def test_pathological_ast_error_is_non_fatal(fixture_repo: Path, monkeypatch) -> None:
    # a syntactically VALID .py whose AST blows the recursion/memory limit raises
    # RecursionError / MemoryError on parse OR during walk — NOT SyntaxError — so the
    # guard must cover those too, or one such tracked file would crash EVERY verify in
    # the repo. ast.parse and ast.walk share one try; force the error on each in turn.
    for attr in ("parse", "walk"):
        for exc in (RecursionError, MemoryError):
            monkeypatch.setattr(symbol_index.ast, attr, _raiser(exc))
            assert symbol_index.python_symbol_definers(fixture_repo) == {}  # skipped, no crash
            assert _verify(fixture_repo, [LOGIN_CLAIM]) == 0  # verify still seals (born verifiable)
            monkeypatch.undo()


def test_non_string_claim_text_is_non_fatal(fixture_repo: Path) -> None:
    # malformed agent JSON: a non-string `text` must not crash the index path
    # (claims_io does not coerce text; the symbol index tolerates and ignores it)
    bad = Claim(
        id="bad",
        text=123,
        kind="fact",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    assert symbol_index.claim_symbol_watch_paths(fixture_repo, [bad]) == {}


def test_restricted_definer_refuses_seal_then_allow(fixture_repo: Path) -> None:
    # the widened read-set is scope-linted like any other entry: a claim mentioning
    # a symbol DEFINED in a restricted file refuses the seal (exit 6) even though no
    # checker NAMED that file — the behavior documented in README / docs/AGENT_CLAIMS.md.
    (fixture_repo / "pyproject.toml").write_text(
        '[tool.dorian.scopes]\nrestricted = ["src/auth.py"]\n'
    )
    cp = fixture_repo / "claims.json"
    claims_io.save_claims(cp, [LOGIN_CLAIM])
    base = ["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)]

    assert cli.main(base) == 6  # EXIT_SCOPE: verify_token's definer src/auth.py is restricted
    assert not (fixture_repo / "docs/design.md.warrant").exists()

    assert cli.main([*base, "--allow-restricted"]) == 0
    assert (fixture_repo / "docs/design.md.warrant").is_file()


def test_non_git_repo_yields_no_watch(tmp_path: Path) -> None:
    # not a git checkout: the index degrades to {} rather than blocking verify on the
    # gitio.GitError from ls_files (the expansion is strictly additive and non-fatal)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("def widget_factory():\n    return 1\n")
    claim = Claim(
        id="c",
        text="The flow uses widget_factory.",
        kind="fact",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="string:src/m.py::x"),),
    )
    assert symbol_index.claim_symbol_watch_paths(tmp_path, [claim]) == {}


# --- Acceptance A/B with a C4 pytest checker that EXERCISES the symbol ------------------
# The checker is bound only to tests/test_auth.py and never names src/auth.py, so without
# the symbol-definer binding a rename of verify_token in src/auth.py is silent. Because the
# pytest imports the symbol's module, the widened watch makes the rename a real BROKEN.

# checks the symbol's existence at call time (not a module-level `from auth import ...`),
# so a rename FAILs the assertion (exit 1 -> BROKEN) instead of erroring at import.
TEST_AUTH_PY = """import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_verify_token():
    import auth

    assert hasattr(auth, "verify_token"), "verify_token was renamed or removed"
    assert auth.verify_token("signed-token") is True
"""

C4_CLAIM = Claim(
    id="auth-verify-token",
    text="`verify_token` accepts signed access tokens.",
    kind="behavior",
    load_bearing=True,
    checkers=(CheckerSpec(type="C4", program="pytest:tests/test_auth.py::test_verify_token"),),
)


@pytest.fixture
def interpreter_on_path(monkeypatch):
    # the C4 checker spawns bare `python -m pytest`; ensure it resolves an interpreter
    # that has pytest regardless of how this suite itself was invoked (mirrors test_c4.py)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent), prepend=os.pathsep)


@pytest.mark.slow
def test_acceptance_A_c4_checker_watches_and_captures_definer(
    fixture_repo: Path, interpreter_on_path
) -> None:
    write(fixture_repo, "tests/test_auth.py", TEST_AUTH_PY)
    commit_all(fixture_repo, "add a pytest that imports verify_token's module")

    assert _verify(fixture_repo, [C4_CLAIM]) == 0  # born verifiable: the pytest passes now
    claim = _warrant(fixture_repo).claims[0]
    # the C4 checker named only tests/test_auth.py; the index added src/auth.py (the file
    # that DEFINES verify_token) to both the sealed watch and the auto-captured read-set
    assert claim.checkers[0].watch == ("tests/test_auth.py", "src/auth.py")
    assert "src/auth.py" in {e.uri for e in _warrant(fixture_repo).read_set}


@pytest.mark.slow
def test_acceptance_B_c4_definer_rename_breaks_claim(
    fixture_repo: Path, interpreter_on_path
) -> None:
    write(fixture_repo, "tests/test_auth.py", TEST_AUTH_PY)
    commit_all(fixture_repo, "add a pytest that imports verify_token's module")
    assert _verify(fixture_repo, [C4_CLAIM]) == 0
    base = gitio.head_ref(fixture_repo)

    # rename the symbol in its defining file — which no checker NAMED; without the binding
    # fix this drift is invisible. The pytest re-runs and FAILs because the symbol is gone.
    write(fixture_repo, "src/auth.py", AUTH_PY.replace("verify_token", "renamed_token"))

    res = revalidate(fixture_repo, since=base)
    assert res.candidates >= 1  # the definer change selected the claim (was 0 before the fix)
    assert "auth-verify-token" in {cid for _, cid, _ in res.broken}  # a real CATCH, not silence
    assert res.exit_code == 4  # load-bearing claim broke -> warrant REVOKED


# --- Lim #1 (A3): ambiguous symbol skip is made LOUD, not silent -----------------------


def _bindings_flags(fixture_repo: Path, capsys, cid: str) -> list:
    assert cli.main(["--repo", str(fixture_repo), "--json", "bindings", "docs/design.md"]) == 0
    diags = json.loads(capsys.readouterr().out)["claims"]
    return next(c for c in diags if c["claim_id"] == cid)["flags"]


def test_ambiguous_mention_is_flagged_loud_not_silent(fixture_repo: Path, capsys) -> None:
    # two definers for verify_token (ambiguous -> intentionally unbound, low-FP). A
    # LOAD-BEARING claim mentions it but its checker watches an unrelated file: the skip
    # must be LOUD — verify WARNs and `dorian bindings` flags it — never silent.
    write(fixture_repo, "src/dup.py", "def verify_token(token):\n    return bool(token)\n")
    commit_all(fixture_repo, "add a second verify_token definition (ambiguous)")
    lb = Claim(
        id="amb-lb",
        text="Login is gated by verify_token.",
        kind="reference",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    assert _verify(fixture_repo, [lb]) == 0  # ambiguous symbol still seals; it just isn't watched
    assert "verify_token" in capsys.readouterr().err  # verify WARNs on the silent-skip
    assert _warrant(fixture_repo).claims[0].checkers[0].watch == (
        "src/routes.py",
    )  # no watch added
    assert "ambiguous-mention" in _bindings_flags(fixture_repo, capsys, "amb-lb")


def test_ambiguous_mention_flag_is_low_noise(fixture_repo: Path, capsys) -> None:
    write(fixture_repo, "src/dup.py", "def verify_token(token):\n    return bool(token)\n")
    commit_all(fixture_repo, "add a second verify_token definition (ambiguous)")

    # (a) a NON-load-bearing ambiguous mention is not flagged (the flag is load-bearing-only)
    nlb = Claim(
        id="amb-nlb",
        text="Login is gated by verify_token.",
        kind="reference",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    assert _verify(fixture_repo, [nlb]) == 0
    capsys.readouterr()
    assert "ambiguous-mention" not in _bindings_flags(fixture_repo, capsys, "amb-nlb")

    # (b) when a checker ALREADY watches a candidate definer (src/auth.py), it is covered
    cov = Claim(
        id="amb-cov",
        text="Login is gated by verify_token.",
        kind="fact",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="symbol:src/auth.py::verify_token"),),
    )
    assert _verify(fixture_repo, [cov]) == 0
    capsys.readouterr()
    assert "ambiguous-mention" not in _bindings_flags(fixture_repo, capsys, "amb-cov")


# --- Lim #4 (D): read-only `dorian bind-suggest` -------------------------------------------


def _bind_suggest(
    fixture_repo: Path, capsys, claims: list[Claim], repo: Path | None = None
) -> list:
    target = repo or fixture_repo
    cp = target / "claims.json"
    claims_io.save_claims(cp, claims)
    rc = cli.main(["--repo", str(target), "--json", "bind-suggest", "--claims", str(cp)])
    assert rc == 0  # informational, never a gate
    return json.loads(capsys.readouterr().out)["suggestions"]


def test_bind_suggest_emits_unique_definer_not_already_covered(fixture_repo: Path, capsys) -> None:
    # LOGIN_CLAIM mentions verify_token (unique in src/auth.py); its checker names
    # routes.py, not auth.py -> bind-suggest suggests src/auth.py.
    sugg = _bind_suggest(fixture_repo, capsys, [LOGIN_CLAIM])
    assert next(s for s in sugg if s["claim_id"] == "login-gate")["bind"] == ["src/auth.py"]
    assert not (fixture_repo / "docs/design.md.warrant").exists()  # read-only: nothing written

    # a claim whose checker ALREADY names the definer is not suggested (no redundant noise)
    cov = Claim(
        id="cov",
        text="Login is gated by verify_token.",
        kind="fact",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program="symbol:src/auth.py::verify_token"),),
    )
    sugg2 = _bind_suggest(fixture_repo, capsys, [cov])
    assert all(s["claim_id"] != "cov" or s["bind"] == [] for s in sugg2)


def test_bind_suggest_shows_ambiguous_and_degrades_on_non_git(
    fixture_repo: Path, capsys, tmp_path: Path
) -> None:
    write(fixture_repo, "src/dup.py", "def verify_token(token):\n    return bool(token)\n")
    commit_all(fixture_repo, "ambiguous verify_token")
    lb = Claim(
        id="amb",
        text="Login is gated by verify_token.",
        kind="fact",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    s = next(x for x in _bind_suggest(fixture_repo, capsys, [lb]) if x["claim_id"] == "amb")
    assert s["bind"] == []  # ambiguous -> not bound (low-FP)
    assert "verify_token" in s["ambiguous"]

    # a non-git repo degrades to no suggestions, exit 0 (never blocks on the index)
    nongit = tmp_path / "x"
    nongit.mkdir()
    assert _bind_suggest(fixture_repo, capsys, [LOGIN_CLAIM], repo=nongit) == []


# --- Lim #2 (B2): pyproject [project.scripts] -> target-file index --------------------------

_SCRIPT_PROJECT = (
    '[project]\nname = "x"\nversion = "0"\n\n[project.scripts]\nmytool = "pkg.cli:main"\n'
)
_SCRIPT_CLAIM = Claim(
    id="cli-claim",
    text="The `mytool` command is the entry point.",
    kind="reference",
    load_bearing=True,
    checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
)


def test_pyproject_script_binds_target_file(fixture_repo: Path) -> None:
    # a console-script entry point names module:function; a claim mentioning the script
    # binds its target file (unambiguous by construction — TOML keys can't collide).
    write(fixture_repo, "pkg/cli.py", "def main():\n    return 0\n")
    write(fixture_repo, "pyproject.toml", _SCRIPT_PROJECT)
    commit_all(fixture_repo, "add a console-script entry point")
    assert _verify(fixture_repo, [_SCRIPT_CLAIM]) == 0
    w = _warrant(fixture_repo)
    assert w.claims[0].checkers[0].watch == ("src/routes.py", "pkg/cli.py")
    assert "pkg/cli.py" in {e.uri for e in w.read_set}


def test_pyproject_script_restricted_target_refuses_seal(fixture_repo: Path) -> None:
    write(fixture_repo, "pkg/cli.py", "def main():\n    return 0\n")
    write(
        fixture_repo,
        "pyproject.toml",
        _SCRIPT_PROJECT + '\n[tool.dorian.scopes]\nrestricted = ["pkg/cli.py"]\n',
    )
    commit_all(fixture_repo, "console script with a restricted target")
    cp = fixture_repo / "claims.json"
    claims_io.save_claims(cp, [_SCRIPT_CLAIM])
    base = ["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)]
    assert cli.main(base) == 6  # the inferred script target is restricted -> fail closed
    assert cli.main([*base, "--allow-restricted"]) == 0


def test_pyproject_script_rename_target_makes_candidate(fixture_repo: Path) -> None:
    write(fixture_repo, "pkg/cli.py", "def main():\n    return 0\n")
    write(fixture_repo, "pyproject.toml", _SCRIPT_PROJECT)
    commit_all(fixture_repo, "console script")
    assert _verify(fixture_repo, [_SCRIPT_CLAIM]) == 0
    base = gitio.head_ref(fixture_repo)
    write(fixture_repo, "pkg/cli.py", "def renamed():\n    return 0\n")  # target gone
    res = revalidate(fixture_repo, since=base)
    assert res.candidates >= 1  # the target-file change selected the claim
    rechecked = {
        cid for grp in (res.passed, res.broken, res.relocated, res.errored) for _, cid, _ in grp
    }
    assert "cli-claim" in rechecked


# --- Lim #5 (E1): trigger-only coverage is made visible (advisory, never a gate) -----------


def test_trigger_only_symbol_flag_when_no_checker_exercises_definer(
    fixture_repo: Path, capsys
) -> None:
    # a LOAD-BEARING claim mentions verify_token (unique in src/auth.py); its checker
    # inspects routes.py, so src/auth.py is a re-check TRIGGER no checker verifies — the
    # gap the binding fix leaves (trigger != truth). It must be VISIBLE, not silent.
    lb = Claim(
        id="trig",
        text="Login is gated by verify_token.",
        kind="reference",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    )
    assert _verify(fixture_repo, [lb]) == 0
    capsys.readouterr()
    assert "trigger-only-symbol" in _bindings_flags(fixture_repo, capsys, "trig")
    # advisory only: the flag changes NO state — the claim is VERIFIED, warrant TRUSTED
    assert cli.main(["--repo", str(fixture_repo), "--json", "status", "docs/design.md"]) == 0
    assert json.loads(capsys.readouterr().out)["warrants"][0]["claim_states"] == {"VERIFIED": 1}


def test_trigger_only_flag_clears_when_a_checker_names_the_definer(
    fixture_repo: Path, capsys
) -> None:
    # a checker that DIRECTLY verifies the symbol's file is truth-cover, not trigger-only
    cov = Claim(
        id="cov",
        text="Login is gated by verify_token.",
        kind="fact",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program="symbol:src/auth.py::verify_token"),),
    )
    assert _verify(fixture_repo, [cov]) == 0
    capsys.readouterr()
    assert "trigger-only-symbol" not in _bindings_flags(fixture_repo, capsys, "cov")


# --- Lim #3 (C): `dorian rebind` upgrades an old warrant's watches (revalidate stays blind) -


def _seal_prefix_style(fixture_repo: Path):
    # simulate a PRE-binding-fix warrant: seal with extra_watch=None so the symbol
    # definer (src/auth.py) is NOT watched and a change there would be silently skipped.
    from dorian.capture.manual import parse_manual
    from dorian.seal import seal_artifact

    return seal_artifact(
        fixture_repo, "docs/design.md", parse_manual(["src/routes.py"], fixture_repo), [LOGIN_CLAIM]
    )


def test_rebind_widens_old_warrant_watch_and_supersedes(fixture_repo: Path) -> None:
    old = _seal_prefix_style(fixture_repo)
    assert old.claims[0].checkers[0].watch == ("src/routes.py",)  # narrow (pre-fix)

    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 0
    new = _warrant(fixture_repo)
    assert new.claims[0].checkers[0].watch == (
        "src/routes.py",
        "src/auth.py",
    )  # widened, not shrunk
    assert new.supersedes == old.id  # lineage preserved for blast/recall
    assert "src/auth.py" in {e.uri for e in new.read_set}


def test_rebind_refuses_to_launder_a_now_false_claim(fixture_repo: Path) -> None:
    _seal_prefix_style(fixture_repo)
    # the claim's fact is now false; rebind re-runs every checker (born verifiable) and
    # must REFUSE -> a stale warrant is never laundered into a fresh TRUSTED.
    write(fixture_repo, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""))
    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 4


def test_rebind_preserves_producer_and_keeps_captured_readset(fixture_repo: Path) -> None:
    # a warrant whose producing run was a real agent (not "manual") and which captured a
    # dependency (src/extra.py) that no checker names. rebind widens the symbol watch but
    # must NOT falsify the producer or silently drop the captured read-set entry: the
    # warrant's hashed "what this run read" record is an honesty artifact, and the command's
    # own docstring promises existing watches are kept.
    from dataclasses import replace

    from dorian.capture.manual import parse_manual
    from dorian.model import ProducedBy
    from dorian.seal import seal_artifact

    write(fixture_repo, "src/extra.py", "WIDGET = 1\n")  # defines no symbol; pure read-set dep
    commit_all(fixture_repo, "add a captured-but-unwatched dependency")
    rs = parse_manual(["src/routes.py", "src/extra.py"], fixture_repo)
    rs = replace(rs, produced_by=ProducedBy(runner="agent-x", captured_at="2026-01-01T00:00:00Z"))
    old = seal_artifact(fixture_repo, "docs/design.md", rs, [LOGIN_CLAIM])

    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 0
    new = _warrant(fixture_repo)
    assert new.produced_by.runner == "agent-x"  # producer preserved, not rewritten to "manual"
    uris = {e.uri for e in new.read_set}
    assert "src/extra.py" in uris  # deliberately-captured dependency is NOT dropped
    assert "src/auth.py" in uris  # the new symbol definer is added
    assert new.claims[0].checkers[0].watch == ("src/routes.py", "src/auth.py")  # widened
    assert new.supersedes == old.id  # lineage preserved


def test_rebind_is_idempotent_when_nothing_new_to_widen(fixture_repo: Path) -> None:
    # the first rebind widens (mints a new id superseding the pre-fix warrant); a second
    # rebind has nothing new to bind, so it is a no-op that keeps the same content-addressed
    # id rather than churning the sidecar and growing the supersede chain on every run.
    _seal_prefix_style(fixture_repo)
    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 0
    id_after_first = _warrant(fixture_repo).id

    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 0
    assert _warrant(fixture_repo).id == id_after_first  # second rebind is an idempotent no-op


def test_rebind_refuses_c1_span_claims(fixture_repo: Path) -> None:
    # C1 span claims bind a read-set entry (an artifact span), not a code file, so they are
    # not auto-rebindable; rebind must refuse with a usage error (exit 2) and write nothing,
    # rather than silently re-seal or no-op (the command's documented contract).
    from dorian.capture.manual import parse_manual
    from dorian.model import Anchor, CheckerSpec, Claim
    from dorian.seal import seal_artifact

    c1 = Claim(
        id="span",
        text="Token verification lives in src/auth.py and uses RS256.",
        kind="fact",
        load_bearing=True,
        anchor=Anchor(3, 3, "uses RS256"),
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C1", program="rs-0"),),
    )
    seal_artifact(
        fixture_repo, "docs/design.md", parse_manual(["docs/design.md:L3-3"], fixture_repo), [c1]
    )
    before = (fixture_repo / "docs/design.md.warrant").read_bytes()

    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 2
    assert (fixture_repo / "docs/design.md.warrant").read_bytes() == before  # sidecar untouched


def test_rebind_assigns_collision_free_readset_ids(fixture_repo: Path) -> None:
    # a read-set with NON-contiguous ids (rs-0, rs-2) must not collide when rebind appends the
    # new definer entry: new ids are derived to avoid every existing id, not from list length.
    from dataclasses import replace

    from dorian.capture.manual import parse_manual
    from dorian.seal import seal_artifact

    write(fixture_repo, "src/extra.py", "WIDGET = 1\n")
    commit_all(fixture_repo, "add a read-set dependency")
    rs = parse_manual(["src/routes.py", "src/extra.py"], fixture_repo)
    e0, e1 = rs.entries
    rs = replace(rs, entries=(e0, replace(e1, id="rs-2")))  # non-contiguous: rs-0, rs-2
    seal_artifact(fixture_repo, "docs/design.md", rs, [LOGIN_CLAIM])

    assert cli.main(["--repo", str(fixture_repo), "rebind", "docs/design.md"]) == 0
    ids = [e.id for e in _warrant(fixture_repo).read_set]
    assert len(ids) == len(set(ids))  # no duplicate ids (a len-based scheme would reuse rs-2)
    assert "src/auth.py" in {e.uri for e in _warrant(fixture_repo).read_set}  # definer added


def test_revalidate_stays_symbol_blind() -> None:
    # the permanent design constraint: revalidate never scans symbols / imports the index;
    # it works only because rebind (or verify) baked better watches into the sidecar.
    import dorian.revalidate as _rv

    src = (Path(_rv.__file__)).read_text(encoding="utf-8")
    assert "symbol_index" not in src
    assert "import ast" not in src and "\nimport ast" not in src
