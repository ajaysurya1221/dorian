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


# Live doc surfaces that must reflect the shipped PyPI release. dorian-vwp 1.0.0
# went live on PyPI 2026-06-16; docs that still say the release hasn't happened
# (pre-PyPI "install from source until..." framing, or an rc2 latest stamp) are
# self-refuting for a verification tool. Historical references in CHANGELOG and
# archive/ are legitimate provenance and are deliberately NOT scanned here.
_LIVE_PYPI_DOC_SURFACES = (
    "README.md",
    "action/action.yml",
    "action/README.md",
    "docs/BENCHMARK_CURRENT.md",
    "docs/ROADMAP_BACKLOG.md",
)

# Phrases that deny the shipped release. The "first PyPI release" family is
# matched case-insensitively so capitalized ("Until the first PyPI release") and
# lowercase ("until the first PyPI release") variants are both caught; the rc2
# stamp is matched literally.
_STALE_PREPYPI_PHRASES = (
    "first PyPI release is on the roadmap",
    "after the first PyPI release",
    "until the first PyPI release",
)
_STALE_RC_LITERAL = "v1.0.0rc2"


def test_no_stale_prepypi_or_rc_vocabulary_in_live_docs() -> None:
    offenders: list[str] = []
    for rel in _LIVE_PYPI_DOC_SURFACES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for phrase in _STALE_PREPYPI_PHRASES:
                if phrase.lower() in lowered:
                    offenders.append(f"{rel}:{lineno}: {phrase!r} -> {line.strip()}")
            if _STALE_RC_LITERAL in line:
                offenders.append(f"{rel}:{lineno}: {_STALE_RC_LITERAL!r} -> {line.strip()}")
    assert not offenders, "stale pre-PyPI / rc2 vocabulary in live docs:\n" + "\n".join(offenders)
