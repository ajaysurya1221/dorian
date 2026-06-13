"""The README's "Try it in 30 seconds" recipe, executed as a black box.

This pins the headline runnable example to reality: it runs the exact sequence the README
shows (out-of-process, via `python -m dorian`) and asserts the observable result, and it
checks the README still contains that command — so the demo a new user copy-pastes can
never silently become a broken claim. (A tool whose whole pitch is "don't ship false
claims" must not ship a false claim in its own README.)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}

# the claims.json the README's recipe writes (kept identical to the README block)
_CLAIMS_JSON = (
    '{"claims": [\n'
    '  {"id": "handler-exists", "text": "handler() lives in app.py.",\n'
    '   "kind": "behavior", "load_bearing": true,\n'
    '   "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}]}\n'
    "]}\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **_GIT_ENV}, check=True, capture_output=True
    )


def _dorian(*args: str, repo: Path) -> subprocess.CompletedProcess:
    # mirror the README recipe exactly: cd into the repo, default --repo=".", relative paths
    cmd = [sys.executable, "-m", "dorian", *args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)


def test_readme_try_it_recipe_runs_end_to_end(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("def handler():\n    return 200\n")
    (repo / "note.md").write_text("# change note\n\n`handler()` lives in app.py.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "app + note")
    (repo / "claims.json").write_text(_CLAIMS_JSON, encoding="utf-8")

    # verify: the claim holds against the real code -> sealed, exit 0
    r = _dorian("verify", "note.md", "--claims", "claims.json", repo=repo)
    assert r.returncode == 0, r.stderr
    assert "verified 1/1 claim(s)" in r.stdout
    assert (repo / "note.md.warrant").is_file()

    # a refactor renames the function the note claims exists; note.md is untouched
    (repo / "app.py").write_text("def renamed():\n    return 200\n")

    r = _dorian("revalidate", "--since", "HEAD", repo=repo)
    assert r.returncode == 4, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "handler-exists" in r.stdout
    assert "BROKEN" in r.stdout
    assert "REVOKED" in r.stdout


def test_readme_still_contains_the_runnable_commands() -> None:
    """If the recipe's commands drift, this fails — keeping the README honest vs the test."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "dorian verify note.md --claims claims.json" in readme
    assert "dorian revalidate --since HEAD" in readme
    assert "symbol:app.py::handler" in readme
