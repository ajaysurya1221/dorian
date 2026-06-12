"""Shared fixtures: a deterministic git fixture repo + a recorded mini-transcript.

The fixture repo mirrors the plan's demo scenario: docs/design.md makes claims about
src/auth.py (RS256 span), src/config.py (TIMEOUT = 30), src/routes.py (/v1/login),
and data/lots.csv (row count / schema / domain) — so every checker type has a
realistic target, and the canonical "3-change commit" can break exactly two claims
while relocating one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-test",
    "GIT_AUTHOR_EMAIL": "test@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-test",
    "GIT_COMMITTER_EMAIL": "test@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

AUTH_PY = '''"""Auth helpers."""


def verify_token(token: str) -> bool:
    """Verify an RS256-signed JWT."""
    algo = "RS256"
    return _check(token, algo)


def _check(token: str, algo: str) -> bool:
    return bool(token) and algo == "RS256"
'''

CONFIG_PY = """TIMEOUT = 30
RETRIES = 3
BASE_URL = "https://api.example.test"
"""

ROUTES_PY = """ROUTES = {
    "/v1/login": "auth.login",
    "/v2/items": "items.list",
}
"""

DESIGN_MD = """# Design

Token verification lives in src/auth.py and uses RS256.

The default request timeout is 30 seconds.

Login is served at /v1/login.

The lots dataset has 4 rows and a status column limited to open/closed.
"""

LOTS_CSV = """lot_id,site,status,loaded_at
L001,athens,open,2026-01-01
L002,berlin,closed,2026-01-02
L003,athens,open,2026-01-03
L004,cairo,open,2026-01-04
"""


def git(repo: Path, *args: str) -> str:
    import os

    env = {**os.environ, **GIT_ENV}
    out = subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def write(repo: Path, rel: str, content: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def commit_all(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "src/auth.py", AUTH_PY)
    write(repo, "src/config.py", CONFIG_PY)
    write(repo, "src/routes.py", ROUTES_PY)
    write(repo, "docs/design.md", DESIGN_MD)
    write(repo, "data/lots.csv", LOTS_CSV)
    commit_all(repo, "initial fixture state")
    return repo


def apply_three_change_commit(repo: Path) -> str:
    """The canonical drift commit: rename auth module (relocation, no break),
    change the timeout default (breaks a quantity claim), delete the /v1/login
    route (breaks a reference claim). docs/design.md is untouched."""
    git(repo, "mv", "src/auth.py", "src/tokens.py")
    write(repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    write(
        repo,
        "src/routes.py",
        ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""),
    )
    return commit_all(repo, "refactor: rename auth, tune timeout, drop legacy login")


def apply_unrelated_commit(repo: Path) -> str:
    """A commit that must produce zero alarms."""
    write(repo, "src/util.py", "def helper():\n    return 42\n")
    return commit_all(repo, "chore: add unrelated helper")


@pytest.fixture
def transcript_file(tmp_path: Path, fixture_repo: Path) -> Path:
    """A minimal Claude Code-shaped session transcript whose tool_use blocks read
    the fixture repo files (shape verified against real transcripts 2026-06-11:
    assistant records carry message.content[] blocks with type=tool_use)."""

    def tu(name: str, **inp) -> dict:
        return {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": f"toolu_{name}", "name": name, "input": inp}]
            },
        }

    records = [
        {"type": "system", "subtype": "session_start"},
        tu("Read", file_path=str(fixture_repo / "src/auth.py")),
        tu("Read", file_path=str(fixture_repo / "src/config.py"), offset=1, limit=2),
        tu("Grep", pattern="/v1/login", path=str(fixture_repo / "src")),
        tu("Bash", command=f"cat {fixture_repo}/data/lots.csv | head -3"),
        tu("Write", file_path=str(fixture_repo / "docs/design.md"), content="..."),
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
    ]
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p
