"""Dogfood: Dorian warrants its own Loop Guard claims, and a mutated fact flips the loop.

Copies the real files the committed dogfood claims reference into a throwaway git repo,
seals them born-verifiable with `dorian verify --strength-gate=fail`, then mutates one
load-bearing fact and shows `dorian loop preflight` flip from CONTINUE to REPAIR. This is
the runnable, honest form of the dogfood (the committed `.warrant` is produced by running
the same verify command outside the sandbox).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from conftest import commit_all, git
from dorian import cli, commands, gitio

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTE = "docs/changes/dorian-loop-guard.md"
CLAIMS = "docs/changes/dorian-loop-guard.claims.json"
# the real files the dogfood claims reference (copied verbatim into the temp repo)
REFERENCED = (
    "src/dorian/loop.py",
    "src/dorian/cli.py",
    "src/dorian/commands.py",
    "docs/DORIAN_LOOP_GUARD.md",
    "docs/LOOP_ENGINEERING_ALIGNMENT.md",
    "src/dorian/templates/claude_code/dorian-loop-guard/SKILL.md",
    "pyproject.toml",
    "README.md",
)


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _dogfood_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for rel in (*REFERENCED, NOTE, CLAIMS):
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, dst)
    commit_all(repo, "dogfood: loop guard artifacts")
    return repo


def test_dogfood_claims_seal_born_verifiable(tmp_path: Path, capsys) -> None:
    repo = _dogfood_repo(tmp_path)
    rc = commands.cmd_verify(
        _ns(
            "--repo",
            str(repo),
            "verify",
            NOTE,
            "--claims",
            str(repo / CLAIMS),
            "--strength-gate=fail",
            "--binding-gate=warn",
        )
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert (repo / (NOTE + ".warrant")).is_file()
    assert "verified 10/10 claim(s)" in out


def test_dogfood_mutation_flips_continue_to_repair(tmp_path: Path, capsys) -> None:
    repo = _dogfood_repo(tmp_path)
    commands.cmd_verify(
        _ns(
            "--repo",
            str(repo),
            "verify",
            NOTE,
            "--claims",
            str(repo / CLAIMS),
            "--strength-gate=fail",
        )
    )
    capsys.readouterr()
    base = gitio.head_ref(repo)

    # clean preflight: nothing changed -> continue
    commands.cmd_loop(
        _ns("--repo", str(repo), "loop", "preflight", "--since", base, "--format", "json")
    )
    clean = json.loads(capsys.readouterr().out)
    assert clean["decision"] == "continue"

    # mutate a warranted load-bearing fact: remove the preflight() definition
    loop_py = repo / "src/dorian/loop.py"
    loop_py.write_text(
        loop_py.read_text(encoding="utf-8").replace("def preflight(", "def preflight_RENAMED("),
        encoding="utf-8",
    )
    commands.cmd_loop(
        _ns("--repo", str(repo), "loop", "preflight", "--since", base, "--format", "json")
    )
    drifted = json.loads(capsys.readouterr().out)
    assert drifted["decision"] == "repair"
    assert any(b["claim_id"] == "loop-engine" for b in drifted["broken_claims"])
