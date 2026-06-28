"""Loop install: idempotent scaffolding of the .claude/skills/dorian-loop-guard bundle."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import git
from dorian import cli, commands

SKILL = ".claude/skills/dorian-loop-guard/SKILL.md"


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo


def _install(capsys, repo: Path, *extra: str) -> tuple[int, dict]:
    rc = commands.cmd_loop(_ns("--repo", str(repo), "--json", "loop", "install", *extra))
    return rc, json.loads(capsys.readouterr().out)


def test_install_scaffolds_skill_bundle(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    rc, data = _install(capsys, repo)
    assert rc == 0
    assert SKILL in data["created"]
    skill = repo / SKILL
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "/dorian-loop-guard" in text
    assert "not a sandbox" in text
    # the example state/action templates ride inside the skill dir by default
    assert (repo / ".claude/skills/dorian-loop-guard/templates/LOOP.md").is_file()
    assert (repo / ".claude/skills/dorian-loop-guard/reference/loop-decisions.md").is_file()
    # but NOT at the repo root unless --with-state / --with-action
    assert not (repo / "LOOP.md").exists()
    assert not (repo / ".github/workflows/dorian-loop.yml").exists()


def test_install_idempotent_without_force(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    _install(capsys, repo)
    edited = "edited by user\n"
    (repo / SKILL).write_text(edited, encoding="utf-8")
    rc, data = _install(capsys, repo)
    assert rc == 0
    assert SKILL in data["skipped"]
    assert data["created"] == []
    assert (repo / SKILL).read_text(encoding="utf-8") == edited  # not clobbered


def test_install_force_overwrites(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    _install(capsys, repo)
    (repo / SKILL).write_text("stale\n", encoding="utf-8")
    rc, data = _install(capsys, repo, "--force")
    assert rc == 0
    assert SKILL in data["overwritten"]
    assert "/dorian-loop-guard" in (repo / SKILL).read_text(encoding="utf-8")


def test_install_with_state_and_action(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    rc, data = _install(capsys, repo, "--with-state", "--with-action")
    assert rc == 0
    for p in ("LOOP.md", "STATE.md", "loop-run-log.md", ".github/workflows/dorian-loop.yml"):
        assert p in data["created"]
        assert (repo / p).is_file()


def test_install_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    rc, data = _install(capsys, repo, "--dry-run")
    assert rc == 0
    assert data["dry_run"] is True
    assert SKILL in data["created"]  # planned
    assert not (repo / SKILL).exists()  # but not written


def test_install_print_next_steps_no_writes(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    rc = commands.cmd_loop(_ns("--repo", str(repo), "loop", "install", "--print-next-steps"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Trust boundary" in out
    assert not (repo / SKILL).exists()
