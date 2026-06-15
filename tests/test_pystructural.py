"""C3 Python structural checkers: `py-signature:` and `py-const:`.

These close two documented weak-verdict ceilings of `symbol:`/`string:`/`regex:`:
- `symbol:` proves a name still EXISTS; it cannot see a signature change.
- `string:`/`regex:` search raw file text, so a fact surviving only in a comment,
  docstring, or dead literal still passes.

Both new forms parse the target file's AST (stdlib `ast`), so:
- they are tolerant of formatting (whitespace, quote style, int base) because the
  comparison is over parsed structure / literal VALUES, never raw text;
- they cannot be fooled by a mention in a comment or docstring (the AST has no
  such node for the claimed symbol);
- they FAIL on a real structural/value drift, and ERROR (never FAIL) when the
  checker itself cannot run (unparseable target, malformed program, non-literal
  constant), so a degenerate program never produces a vacuous PASS;
- they remain READ-ONLY and never execute user code.

The honest ceiling stays visible: a body-only ("gutted body") change keeps the
signature identical, so `py-signature:` PASSes — only a behavior checker (C4) catches
that. The test for it asserts PASS and the docs state the ceiling.
"""

from __future__ import annotations

from pathlib import Path

from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import CheckerSpec, Claim


def _run(repo: Path, program: str) -> object:
    claim = Claim(
        id="c",
        text="x",
        kind="behavior",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program=program),),
    )
    return run_checker(CheckContext(repo=repo, claim=claim), 0)


def _w(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# --- py-signature -------------------------------------------------------------


AUTH = '''"""mod."""


def verify_token(token: str) -> bool:
    """Verify an RS256 JWT."""
    return bool(token)
'''


def test_py_signature_unchanged_passes(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", AUTH)
    assert (
        _run(tmp_path, "py-signature:m.py::verify_token::token: str -> bool").verdict
        is Verdict.PASS
    )


def test_py_signature_names_only_ignores_unspecified_annotations(tmp_path: Path) -> None:
    """A spec that lists only param names compares only names/order/kind — the
    annotation and return are NOT specified, so they are not compared."""
    _w(tmp_path, "m.py", AUTH)
    assert _run(tmp_path, "py-signature:m.py::verify_token::token").verdict is Verdict.PASS


def test_py_signature_param_rename_fails(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", AUTH)
    res = _run(tmp_path, "py-signature:m.py::verify_token::tok")
    assert res.verdict is Verdict.FAIL
    assert "signature" in res.detail


def test_py_signature_param_count_and_order_fail(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "def f(a, b):\n    return a\n")
    assert _run(tmp_path, "py-signature:m.py::f::a").verdict is Verdict.FAIL  # missing b
    assert _run(tmp_path, "py-signature:m.py::f::b, a").verdict is Verdict.FAIL  # reordered
    assert _run(tmp_path, "py-signature:m.py::f::a, b").verdict is Verdict.PASS


def test_py_signature_default_change(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "def f(x=1):\n    return x\n")
    assert _run(tmp_path, "py-signature:m.py::f::x=2").verdict is Verdict.FAIL
    assert _run(tmp_path, "py-signature:m.py::f::x=1").verdict is Verdict.PASS
    # a spec that omits the default does not compare it (only names checked)
    assert _run(tmp_path, "py-signature:m.py::f::x").verdict is Verdict.PASS


def test_py_signature_return_annotation_change(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", AUTH)
    assert _run(tmp_path, "py-signature:m.py::verify_token::token -> int").verdict is Verdict.FAIL
    assert _run(tmp_path, "py-signature:m.py::verify_token::token -> bool").verdict is Verdict.PASS


def test_py_signature_formatting_only_passes(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "def f( x ,y ,  z ):\n    return x\n")
    assert _run(tmp_path, "py-signature:m.py::f::x, y, z").verdict is Verdict.PASS


def test_py_signature_gutted_body_still_passes_documented_ceiling(tmp_path: Path) -> None:
    """The signature is unchanged but the body is inverted: py-signature PASSes.
    This is the documented trigger-vs-truth ceiling — only a behavior checker (C4)
    catches a body-only change. The test pins the ceiling so it cannot regress
    into a silent over-promise."""
    _w(tmp_path, "m.py", "def is_admin(user):\n    return user.role == 'admin'\n")
    before = _run(tmp_path, "py-signature:m.py::is_admin::user")
    _w(tmp_path, "m.py", "def is_admin(user):\n    return True  # gutted\n")
    after = _run(tmp_path, "py-signature:m.py::is_admin::user")
    assert before.verdict is Verdict.PASS and after.verdict is Verdict.PASS


def test_py_signature_missing_function_fails(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", AUTH)
    res = _run(tmp_path, "py-signature:m.py::nope::x")
    assert res.verdict is Verdict.FAIL
    assert "missing" in res.detail


def test_py_signature_async_flag(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "async def fetch(url):\n    return url\n")
    assert _run(tmp_path, "py-signature:m.py::fetch::async url").verdict is Verdict.PASS
    # async not specified -> not compared (sync/async both accepted)
    assert _run(tmp_path, "py-signature:m.py::fetch::url").verdict is Verdict.PASS
    # require async on a sync function -> FAIL
    _w(tmp_path, "m.py", "def fetch(url):\n    return url\n")
    assert _run(tmp_path, "py-signature:m.py::fetch::async url").verdict is Verdict.FAIL


def test_py_signature_method_via_dotted_qualname(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "class A:\n    def login(self, user, pw):\n        return True\n")
    assert _run(tmp_path, "py-signature:m.py::A.login::self, user, pw").verdict is Verdict.PASS
    assert _run(tmp_path, "py-signature:m.py::A.login::self, user").verdict is Verdict.FAIL


def test_py_signature_unparseable_target_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "def f(:::\n")  # syntax error
    assert _run(tmp_path, "py-signature:m.py::f::x").verdict is Verdict.ERROR


def test_py_signature_bad_spec_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", AUTH)
    assert _run(tmp_path, "py-signature:m.py::verify_token::((bad").verdict is Verdict.ERROR
    # empty needle (no qualname) is a bad program
    assert _run(tmp_path, "py-signature:m.py::").verdict is Verdict.ERROR


def test_py_signature_missing_file_is_fail(tmp_path: Path) -> None:
    assert _run(tmp_path, "py-signature:gone.py::f::x").verdict is Verdict.FAIL


def test_py_signature_path_escape_is_error(tmp_path: Path) -> None:
    assert _run(tmp_path, "py-signature:../../etc/passwd::f::x").verdict is Verdict.ERROR


def test_py_signature_comment_cannot_create_false_pass(tmp_path: Path) -> None:
    """A function that exists only as text inside a comment is not in the AST."""
    _w(tmp_path, "m.py", "# def ghost(a, b): pass\nVALUE = 1\n")
    assert _run(tmp_path, "py-signature:m.py::ghost::a, b").verdict is Verdict.FAIL


# --- py-const -----------------------------------------------------------------

CONFIG = 'TIMEOUT = 30\nRETRIES = 3\nALGO = "RS256"\nPORT: int = 8080\n'


def test_py_const_unchanged_passes(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG)
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.PASS


def test_py_const_value_change_fails(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    res = _run(tmp_path, "py-const:c.py::TIMEOUT::30")
    assert res.verdict is Verdict.FAIL
    assert "value" in res.detail or "const" in res.detail


def test_py_const_formatting_and_base_tolerant(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", "TIMEOUT  =  0x1E\n")  # hex 30, extra spaces
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.PASS


def test_py_const_string_quote_tolerant(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG)
    assert _run(tmp_path, 'py-const:c.py::ALGO::"RS256"').verdict is Verdict.PASS
    assert _run(tmp_path, "py-const:c.py::ALGO::'RS256'").verdict is Verdict.PASS
    assert _run(tmp_path, 'py-const:c.py::ALGO::"HS256"').verdict is Verdict.FAIL


def test_py_const_annassign(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG)
    assert _run(tmp_path, "py-const:c.py::PORT::8080").verdict is Verdict.PASS
    assert _run(tmp_path, "py-const:c.py::PORT::9090").verdict is Verdict.FAIL


def test_py_const_class_attribute_via_dotted(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", "class C:\n    LIMIT = 5\n")
    assert _run(tmp_path, "py-const:c.py::C.LIMIT::5").verdict is Verdict.PASS
    assert _run(tmp_path, "py-const:c.py::C.LIMIT::6").verdict is Verdict.FAIL


def test_py_const_missing_is_fail(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG)
    res = _run(tmp_path, "py-const:c.py::NOPE::1")
    assert res.verdict is Verdict.FAIL
    assert "missing" in res.detail


def test_py_const_non_literal_rhs_is_error(tmp_path: Path) -> None:
    """A non-literal RHS cannot be compared to a literal value: ERROR (the checker
    cannot determine the value), never a vacuous PASS or a false FAIL."""
    _w(tmp_path, "c.py", "TIMEOUT = compute_timeout()\n")
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.ERROR


def test_py_const_bad_expected_value_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "c.py", CONFIG)
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::not-a-literal(").verdict is Verdict.ERROR


def test_py_const_comment_and_docstring_survival_does_not_pass(tmp_path: Path) -> None:
    """The value surviving only in a comment or docstring is not an assignment."""
    _w(tmp_path, "c.py", '"""TIMEOUT = 30 in the docstring."""\n# TIMEOUT = 30\nOTHER = 1\n')
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.FAIL


def test_py_const_rejects_value_type_drift(tmp_path: Path) -> None:
    """The 'strong value verifier' must not let a value's TYPE drift past on Python ==:
    30 != 30.0, 1 != True, 0 != False. Otherwise a bool flag silently becoming an int, or
    an int timeout becoming a float, would re-verify green."""
    _w(tmp_path, "c.py", "TIMEOUT = 30.0\nFLAG = 1\nZERO = 0\n")
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.FAIL  # int vs float
    assert _run(tmp_path, "py-const:c.py::FLAG::True").verdict is Verdict.FAIL  # int vs bool
    assert _run(tmp_path, "py-const:c.py::ZERO::False").verdict is Verdict.FAIL  # int vs bool
    # same value AND type still passes
    _w(tmp_path, "c.py", "TIMEOUT = 30\nRATE = 0.5\nFLAG = True\n")
    assert _run(tmp_path, "py-const:c.py::TIMEOUT::30").verdict is Verdict.PASS
    assert _run(tmp_path, "py-const:c.py::RATE::0.5").verdict is Verdict.PASS
    assert _run(tmp_path, "py-const:c.py::FLAG::True").verdict is Verdict.PASS


# --- end-to-end: the new forms bind, seal born-verifiable, and re-check ---------


def test_structural_forms_verify_seal_and_revalidate(fixture_repo: Path) -> None:
    """A py-signature, a py-const, and a code: claim auto-capture their file, seal
    born-verifiable (all hold now), and on the canonical drift commit:
    - the renamed-but-unchanged signature stays VERIFIED (rename-resolved),
    - the changed constant and the removed route fold BROKEN -> REVOKED (exit 4)."""
    import json

    from conftest import apply_three_change_commit, git
    from dorian import cli

    claims = {
        "claims": [
            {
                "id": "vt-sig",
                "text": "verify_token(token) is defined in src/auth.py.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [
                    {
                        "type": "C3",
                        "program": "py-signature:src/auth.py::verify_token::token: str -> bool",
                    }
                ],
            },
            {
                "id": "timeout-30",
                "text": "The default request timeout is 30 seconds.",
                "kind": "quantity",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "py-const:src/config.py::TIMEOUT::30"}],
            },
            {
                "id": "login-route",
                "text": "Login is served at /v1/login.",
                "kind": "reference",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "code:src/routes.py::/v1/login"}],
            },
        ]
    }
    cp = fixture_repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    base = git(fixture_repo, "rev-parse", "HEAD")

    assert (
        cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)])
        == 0
    )
    assert (fixture_repo / "docs/design.md.warrant").is_file()

    apply_three_change_commit(fixture_repo)
    rc = cli.main(["--repo", str(fixture_repo), "revalidate", "--since", base])
    assert rc == cli.EXIT_REVOKED  # a load-bearing claim broke -> exit 4


def test_new_form_error_folds_to_errored_not_broken(fixture_repo: Path) -> None:
    """A py-const claim whose RHS becomes NON-LITERAL on a later edit ERRORs (the value
    cannot be determined) — it must fold to ERRORED (exit 5), never BROKEN. Pins the
    ERROR-never-BROKEN invariant end-to-end for the new C3 forms."""
    import json

    from conftest import commit_all, git, write
    from dorian import cli
    from dorian.revalidate import revalidate

    claims = {
        "claims": [
            {
                "id": "timeout",
                "text": "The default request timeout is 30 seconds.",
                "kind": "quantity",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "py-const:src/config.py::TIMEOUT::30"}],
            }
        ]
    }
    (fixture_repo / "claims.json").write_text(json.dumps(claims), encoding="utf-8")
    base = git(fixture_repo, "rev-parse", "HEAD")
    assert (
        cli.main(
            [
                "--repo",
                str(fixture_repo),
                "verify",
                "docs/design.md",
                "--claims",
                str(fixture_repo / "claims.json"),
            ]
        )
        == 0
    )
    write(fixture_repo, "src/config.py", "TIMEOUT = compute_timeout()\nRETRIES = 3\n")
    commit_all(fixture_repo, "timeout becomes a non-literal")
    res = revalidate(fixture_repo, since=base)
    assert {cid for _, cid, _ in res.errored} == {"timeout"}
    assert res.broken == []  # ERROR is never BROKEN
    assert res.exit_code == cli.EXIT_ERRORED
