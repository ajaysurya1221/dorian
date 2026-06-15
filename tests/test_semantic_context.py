"""C3 `code:` — regex over comment/docstring-stripped Python.

`string:`/`regex:` search raw file text, so a fact that survives only in a comment,
docstring, or dead literal passes. `code:` parses the file and blanks comments and
docstrings before matching, so the SAME fact in actual code (an assignment, a call
arg, a dict-key route string, a decorator) still matches, but a comment/docstring
survival does not. It is Python-only (the comment/docstring model is Python's);
a non-Python target ERRORs (cannot run), never silently passes.

These pin the WP4 acceptance matrix and the contrast against raw `string:`/`regex:`.
"""

from __future__ import annotations

from pathlib import Path

from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import CheckerSpec, Claim


def _run(repo: Path, program: str) -> object:
    claim = Claim(
        id="c",
        text="x",
        kind="reference",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program=program),),
    )
    return run_checker(CheckContext(repo=repo, claim=claim), 0)


def _w(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_code_matches_real_assignment(tmp_path: Path) -> None:
    _w(tmp_path, "config.py", "TIMEOUT = 30\n")
    assert _run(tmp_path, r"code:config.py::TIMEOUT\s*=\s*30").verdict is Verdict.PASS


def test_code_formatting_tolerant(tmp_path: Path) -> None:
    _w(tmp_path, "config.py", "TIMEOUT=30\n")
    assert _run(tmp_path, r"code:config.py::TIMEOUT\s*=\s*30").verdict is Verdict.PASS


def test_code_ignores_comment_survival(tmp_path: Path) -> None:
    """The fact lives ONLY in a comment: raw string:/regex: pass, code: FAILs."""
    src = "# TIMEOUT = 30 (old default)\nTIMEOUT = 10\n"
    _w(tmp_path, "config.py", src)
    # raw text search still sees the comment -> PASS (the false-pass class)
    assert _run(tmp_path, r"regex:config.py::TIMEOUT\s*=\s*30").verdict is Verdict.PASS
    # code: ignores the comment -> FAIL (no real assignment of 30)
    res = _run(tmp_path, r"code:config.py::TIMEOUT\s*=\s*30")
    assert res.verdict is Verdict.FAIL
    assert "code_missing" in res.detail


def test_code_ignores_docstring_survival(tmp_path: Path) -> None:
    src = '"""The default TIMEOUT = 30 historically."""\nTIMEOUT = 10\n'
    _w(tmp_path, "config.py", src)
    assert _run(tmp_path, r"string:config.py::TIMEOUT = 30").verdict is Verdict.PASS  # raw
    assert _run(tmp_path, r"code:config.py::TIMEOUT\s*=\s*30").verdict is Verdict.FAIL  # semantic


def test_code_keeps_real_string_literals_route(tmp_path: Path) -> None:
    """A route path lives inside a real string literal (dict key) — kept, not a
    docstring. code: must still find it."""
    _w(tmp_path, "routes.py", 'ROUTES = {\n    "/v1/login": "auth.login",\n}\n')
    assert _run(tmp_path, "code:routes.py::/v1/login").verdict is Verdict.PASS


def test_code_keeps_decorator_argument(tmp_path: Path) -> None:
    _w(tmp_path, "api.py", '@app.route("/health")\ndef health():\n    return "ok"\n')
    assert _run(tmp_path, "code:api.py::/health").verdict is Verdict.PASS


def test_code_keeps_call_argument(tmp_path: Path) -> None:
    _w(tmp_path, "api.py", "connect(timeout=30, retries=3)\n")
    assert _run(tmp_path, r"code:api.py::timeout\s*=\s*30").verdict is Verdict.PASS


def test_code_non_python_target_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "notes.txt", "this is not python: def x(::\n")
    res = _run(tmp_path, "code:notes.txt::def x")
    assert res.verdict is Verdict.ERROR
    assert "unparseable" in res.detail


def test_code_missing_file_is_fail(tmp_path: Path) -> None:
    assert _run(tmp_path, "code:gone.py::anything").verdict is Verdict.FAIL


def test_code_over_length_pattern_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "x = 1\n")
    assert _run(tmp_path, "code:m.py::" + ("a" * 600)).verdict is Verdict.ERROR


def test_code_bad_regex_is_error(tmp_path: Path) -> None:
    _w(tmp_path, "m.py", "x = 1\n")
    assert _run(tmp_path, "code:m.py::(unclosed").verdict is Verdict.ERROR


def test_code_path_escape_is_error(tmp_path: Path) -> None:
    assert _run(tmp_path, "code:../../etc/passwd::root").verdict is Verdict.ERROR
