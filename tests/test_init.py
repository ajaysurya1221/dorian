"""`dorian init`: first-run scaffolding for the golden path.

`init` writes three files — a born-verifiable starter `claims.json`, the change
note they back, and a GitHub Action workflow — so a first-time user reaches a
sealed warrant in minutes. It writes files only: it never runs a checker, never
executes code, never writes outside the repo root, and never overwrites an
existing file without `--force`. The load-bearing test here is that the starter
claim it scaffolds actually *seals green* end to end (`init` -> `verify` exit 0):
a tool whose pitch is "don't ship false claims" must not ship a false scaffold.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dorian import __version__, claims_io, init
from dorian.cli import main
from dorian.model import CheckerSpec
from dorian.policy import executable_kind

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
    return subprocess.run(
        [sys.executable, "-m", "dorian", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _seed_repo(repo: Path, *, name: str = "demo-app", readme: bool = True) -> None:
    """A minimal but realistic Python repo: a pyproject with a project name."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    if readme:
        (repo / "README.md").write_text("# demo-app\n", encoding="utf-8")


def test_init_creates_the_three_scaffold_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)

    assert main(["--repo", str(repo), "init"]) == 0

    claims = repo / init.CLAIMS_FILE
    note = repo / init.NOTE_FILE
    workflow = repo / init.WORKFLOW_FILE
    assert claims.is_file()
    assert note.is_file()
    assert workflow.is_file()

    # claims.json is structurally valid (round-trips through the real loader)
    loaded = claims_io.load_claims(claims)
    assert len(loaded) == 1

    # the workflow pins the action to THIS package version (coherent install)
    wf = workflow.read_text(encoding="utf-8")
    assert f"ajaysurya1221/dorian/action@v{__version__}" in wf
    assert "on: [pull_request]" in wf
    assert "actions/checkout" in wf


def test_init_starter_claim_is_non_executable(tmp_path: Path) -> None:
    """init scaffolds a safe-by-default starter: the seeded checker is a
    read-only C3 family (path:/config-value:), never an executable C4/C5."""
    repo = tmp_path / "repo"
    _seed_repo(repo)
    plan = init.build_plan(repo)
    claim = json.loads(_claims_content(plan))["claims"][0]
    for spec in claim["checkers"]:
        assert executable_kind(CheckerSpec.from_dict(spec)) is None


def test_init_scaffold_seals_green_end_to_end(tmp_path: Path) -> None:
    """The golden path: init -> verify exits 0 and writes a warrant. If the
    scaffolded claim did not actually hold, this would fail."""
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed repo")

    r = _dorian("init", repo=repo)
    assert r.returncode == 0, r.stderr

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "dorian init")

    r = _dorian("verify", init.NOTE_FILE, "--claims", init.CLAIMS_FILE, repo=repo)
    assert r.returncode == 0, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "verified 1/1 claim(s)" in r.stdout
    assert (repo / f"{init.NOTE_FILE}.warrant").is_file()


def test_init_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)

    assert main(["--repo", str(repo), "init", "--dry-run"]) == 0
    assert not (repo / init.CLAIMS_FILE).exists()
    assert not (repo / init.NOTE_FILE).exists()
    assert not (repo / init.WORKFLOW_FILE).exists()
    out = capsys.readouterr().out
    assert init.CLAIMS_FILE in out


def test_init_is_idempotent_without_force(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert main(["--repo", str(repo), "init"]) == 0

    # user edits the scaffold; a second init must NOT clobber it
    edited = '{"claims": [], "_mine": true}\n'
    (repo / init.CLAIMS_FILE).write_text(edited, encoding="utf-8")
    assert main(["--repo", str(repo), "init"]) == 0
    assert (repo / init.CLAIMS_FILE).read_text(encoding="utf-8") == edited


def test_init_force_overwrites(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert main(["--repo", str(repo), "init"]) == 0
    (repo / init.CLAIMS_FILE).write_text('{"claims": [], "_mine": true}\n', encoding="utf-8")

    assert main(["--repo", str(repo), "init", "--force"]) == 0
    regenerated = claims_io.load_claims(repo / init.CLAIMS_FILE)
    assert len(regenerated) == 1  # the starter claim is back


def test_init_json_output_is_machine_readable(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    assert main(["--repo", str(repo), "--json", "init"]) == 0
    payload = json.loads(capsys.readouterr().out)
    created = set(payload["created"])
    assert init.CLAIMS_FILE in created
    assert init.NOTE_FILE in created
    assert init.WORKFLOW_FILE in created


def test_init_falls_back_to_path_claim_without_pyproject(tmp_path: Path) -> None:
    """No pyproject: init still scaffolds a born-verifiable claim about a file
    that exists (here, the README)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# hi\n", encoding="utf-8")

    assert main(["--repo", str(repo), "init"]) == 0
    claim = claims_io.load_claims(repo / init.CLAIMS_FILE)[0]
    programs = [c.program for c in claim.checkers]
    assert any(p.startswith("path:") for p in programs)


def _claims_content(plan: init.InitPlan) -> str:
    for f in plan.files:
        if f.path == init.CLAIMS_FILE:
            return f.content
    raise AssertionError("no claims.json in plan")
