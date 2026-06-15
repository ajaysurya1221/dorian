"""Single version story: pyproject, the package, and the CLI must agree.

Version drift (the package saying one thing, pyproject another, the badge a
third) was the headline release-hygiene defect in the v0.10 audit. This pins the
three machine-readable surfaces together so a future bump that misses one fails
here. The README release badge is dynamic (shields.io reads the GitHub release),
so there is no hardcoded README version to check — only that it stays dynamic.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_pyproject_matches_package_dunder() -> None:
    from dorian import __version__

    assert __version__ == _pyproject_version()


def test_cli_version_reports_the_package_version() -> None:
    from dorian import __version__

    out = subprocess.run(
        [sys.executable, "-m", "dorian", "--version"], capture_output=True, text=True
    )
    assert out.returncode == 0
    assert out.stdout.strip() == f"dorian {__version__}"


def test_readme_release_badge_is_dynamic_not_hardcoded() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # the dynamic shields endpoint that tracks the latest GitHub release
    assert "img.shields.io/github/v/release/" in readme
    # and no stale hardcoded release badge like .../badge/release-v0.9-... slipped in
    assert not re.search(r"badge/release-v?\d+\.\d+", readme), "hardcoded version badge found"
