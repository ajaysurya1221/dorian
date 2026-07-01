"""Release gate: build the wheel, install it into a clean venv, run the REAL
`dorian` console script end to end.

This is the only test that exercises the actual packaged entry point
(`[project.scripts] dorian = dorian.cli:main`) from a built artifact in an
isolated environment — the path a `pip install dorian-vwp` user takes. It is
`slow` (a wheel build + venv + install) and skips cleanly if the build toolchain
is unavailable; deselect with `-m 'not slow'`. dorian declares zero runtime
dependencies, so the install needs no network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.slow


def _uv(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", *args], capture_output=True, text=True, cwd=cwd, timeout=300)


@pytest.fixture(scope="module")
def installed_dorian(tmp_path_factory) -> Path:
    """Build the wheel and install it into a throwaway venv; yield the console-script path."""
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH; enable by installing uv")
    work = tmp_path_factory.mktemp("dorian_pkg")
    dist = work / "dist"

    build = _uv("build", "--wheel", "--out-dir", str(dist), cwd=str(REPO_ROOT))
    if build.returncode != 0:
        pytest.skip(f"`uv build` unavailable (offline build backend?): {build.stderr[-400:]}")
    wheels = list(dist.glob("dorian_vwp-*.whl"))
    assert wheels, f"no wheel produced in {dist}: {[p.name for p in dist.iterdir()]}"

    venv = work / "venv"
    made = _uv("venv", str(venv))
    if made.returncode != 0:
        pytest.skip(f"`uv venv` failed: {made.stderr[-400:]}")
    py = venv / "bin" / "python"

    inst = _uv("pip", "install", "--python", str(py), "--no-deps", str(wheels[0]))
    if inst.returncode != 0:
        pytest.skip(f"wheel install failed: {inst.stderr[-400:]}")

    script = venv / "bin" / "dorian"
    assert script.is_file(), f"console script not installed at {script}"
    return script


def test_installed_entrypoint_version(installed_dorian: Path) -> None:
    r = subprocess.run([str(installed_dorian), "--version"], capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.startswith("dorian "), r.stdout


def test_installed_entrypoint_help_lists_verify(installed_dorian: Path) -> None:
    r = subprocess.run([str(installed_dorian), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "verify" in r.stdout and "seal" in r.stdout


def test_installed_entrypoint_full_verify(installed_dorian: Path, tmp_path: Path) -> None:
    """The packaged binary seals a real claim about a real change in a fresh repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    import os

    full_env = {**os.environ, **env}

    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=repo, env=full_env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (repo / "app.py").write_text("def handler():\n    return 200\n")
    (repo / "note.md").write_text("# change\n\n`handler()` lives in app.py.\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    (repo / "claims.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "handler-exists",
                        "text": "handler() lives in app.py.",
                        "kind": "behavior",
                        "load_bearing": True,
                        "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}],
                    }
                ]
            }
        )
    )
    r = subprocess.run(
        [
            str(installed_dorian),
            "--repo",
            str(repo),
            "verify",
            "note.md",
            "--claims",
            str(repo / "claims.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "verified 1/1 claim(s)" in r.stdout
    assert (repo / "note.md.warrant").is_file()


def test_installed_scaffolds_claim_warrants_skill(installed_dorian: Path, tmp_path: Path) -> None:
    """The packaged binary scaffolds the claim-warrants skill from package data —
    proving the templates ship in the wheel and resolve via importlib.resources."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    r = subprocess.run(
        [
            str(installed_dorian),
            "--repo",
            str(repo),
            "claude-code",
            "install-claim-warrants",
            "--with-hook",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    skill = repo / ".claude/skills/dorian-claim-warrants/SKILL.md"
    assert skill.is_file()
    assert (repo / ".claude/hooks/dorian_claim_warrants_stop.py").is_file()
    text = skill.read_text(encoding="utf-8")
    for phrase in ("DRAFT", "not a sandbox", "strength-gate=fail"):
        assert phrase in text


def test_installed_scaffolds_loop_guard_skill(installed_dorian: Path, tmp_path: Path) -> None:
    """The packaged binary scaffolds the loop-guard bundle from package data — proving the
    skill, the state templates, AND the .yml Action example ship in the wheel."""
    repo = tmp_path / "looprepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    r = subprocess.run(
        [
            str(installed_dorian),
            "--repo",
            str(repo),
            "loop",
            "install",
            "--with-state",
            "--with-action",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (repo / ".claude/skills/dorian-loop-guard/SKILL.md").is_file()
    assert (repo / "LOOP.md").is_file()
    assert (repo / ".github/workflows/dorian-loop.yml").is_file()
    text = (repo / ".claude/skills/dorian-loop-guard/SKILL.md").read_text(encoding="utf-8")
    for phrase in ("/dorian-loop-guard", "not a sandbox", "token-free"):
        assert phrase in text


def test_installed_scaffolds_governance_adapter(installed_dorian: Path, tmp_path: Path) -> None:
    """The packaged binary scaffolds the Claude Code governance adapter from package data —
    proving the two host hooks + settings + docs ship in the wheel, and that the installed
    PreToolUse veto carries its exit-2 fail-closed path for a real `pip install dorian-vwp` user."""
    repo = tmp_path / "govrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    r = subprocess.run(
        [str(installed_dorian), "--repo", str(repo), "governance", "install"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    veto = repo / ".claude/hooks/dorian_preflight_veto.py"
    stop = repo / ".claude/hooks/dorian_loop_preflight.py"
    for f in (
        veto,
        stop,
        repo / ".claude/settings.dorian-governance.example.json",
        repo / ".claude/dorian-governance/README.md",
        repo / ".claude/dorian-governance/reference/enforcement-modes.md",
    ):
        assert f.is_file(), f
    veto_text = veto.read_text(encoding="utf-8")
    assert "return 2" in veto_text  # the exit-2 tool-block veto ships in the installed hook
    assert "FAIL CLOSED" in veto_text.upper()
    assert "hookSpecificOutput" in stop.read_text(encoding="utf-8")
