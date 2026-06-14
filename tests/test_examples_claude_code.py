"""The shipped Claude Code example pack, executed as a black box.

`examples/claude-code/` is advertised as a runnable example of the agent-in,
checker-out loop. This runs the *shipped* files (not a copy) end-to-end via
`python -m dorian`: verify seals 2/2 against the real code (exit 0), then a
refactor that renames the function and drops the timeout makes revalidate fold
both claims BROKEN -> REVOKED (exit 4). If the example ever stops working, this
fails — a tool whose pitch is "don't ship false claims" must not ship a false
example.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "claude-code"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, env={**os.environ, **_GIT_ENV}, check=True, capture_output=True
    )


def _dorian(*args: str, repo: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "dorian", *args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)


def test_claude_code_example_pack_runs_end_to_end(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # copy the SHIPPED example files (claims.json paths are repo-root-relative)
    for name in ("app.py", "change-note.md", "claims.json"):
        (repo / name).write_text((EXAMPLE / name).read_text(encoding="utf-8"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "login handler + note")

    # verify: both claims hold against the real code -> sealed, exit 0
    r = _dorian("verify", "change-note.md", "--claims", "claims.json", repo=repo)
    assert r.returncode == 0, r.stderr
    assert "verified 2/2 claim(s)" in r.stdout
    assert (repo / "change-note.md.warrant").is_file()

    # the exact refactor the example README documents: rename the fn, drop the timeout
    (repo / "app.py").write_text(
        'LOGIN_TIMEOUT = 10\n\n\ndef signin(request):\n    return {"ok": True}\n'
    )

    r = _dorian("revalidate", "--since", "HEAD", repo=repo)
    assert r.returncode == 4, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "login-handler-added" in r.stdout
    assert "login-timeout-30s" in r.stdout
    assert r.stdout.count("BROKEN") >= 2
    assert "REVOKED" in r.stdout


def test_example_readme_documents_the_runnable_commands() -> None:
    readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "dorian verify change-note.md --claims claims.json" in readme
    assert "dorian revalidate --since HEAD" in readme
