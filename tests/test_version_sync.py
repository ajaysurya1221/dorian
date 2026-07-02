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


def test_readme_pypi_latest_version_matches_package() -> None:
    """The README's one hardcoded PyPI 'latest: vX.Y.Z' string must name the shipped
    version. Found by the v1.0.2 release judge: the badge is dynamic but the prose
    'PyPI trusted publishing (latest: v1.0.0)' line is a separate hardcoded surface that
    drifts on a version bump — exactly the kind of stale release-state string this file pins.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    version = _pyproject_version()
    mentions = re.findall(r"latest:[^\n]*?v(\d+\.\d+\.\d+)", readme)
    assert mentions, "expected a README 'latest: vX.Y.Z' PyPI mention to pin"
    for found in mentions:
        assert found == version, f"README PyPI 'latest: v{found}' != package version {version}"


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
    # the v1.0.1 audit (Codex FINDING-09) found this narrower variant slipped past the
    # "first PyPI release" family — the README Action snippet said "until the PyPI release".
    "until the PyPI release",
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


# Public copy-paste must pin the dorian Action to an immutable released ref, never the
# mutable @main (Codex FINDING-02). The composite Action lives in this same repo, so a
# README/action-doc snippet telling users `dorian/action@main` ships a moving target.
def test_no_dorian_action_at_main_in_public_snippets() -> None:
    offenders: list[str] = []
    for rel in ("README.md", "action/README.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "dorian/action@main" in line:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, "mutable dorian/action@main in public copy-paste:\n" + "\n".join(
        offenders
    )


# Live copy-paste pins must also track the released version: an immutable but STALE pin
# (e.g. @v1.3.0 shipped in the v1.4.0 README) hands users an action missing the release's
# commands. Asserted against the package version, not the tag (the tag exists only after
# release — the brief merged-but-untagged window is accepted). docs/releases/ and CHANGELOG
# are historical provenance and deliberately not scanned.
_ACTION_PIN_SURFACES = (
    "README.md",
    "action/README.md",
    "docs/CLAUDE_CODE_DORIAN_WORKFLOW.md",
    "docs/SECURITY_AND_SAFE_RUNNERS.md",
)


def test_dorian_action_pins_match_package_version() -> None:
    version = _pyproject_version()
    offenders: list[str] = []
    for rel in _ACTION_PIN_SURFACES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pin in re.findall(r"dorian/action@v(\d+\.\d+\.\d+)", line):
                if pin != version:
                    offenders.append(f"{rel}:{lineno}: @v{pin} != package v{version}")
    assert not offenders, "stale dorian/action version pins:\n" + "\n".join(offenders)


# The attestation-interop example must not pin a fixed dorianVersion (Codex FINDING-07): a
# hardcoded "1.0.x" silently drifts every release. It is kept version-neutral instead.
def test_attestation_interop_dorian_version_is_version_neutral() -> None:
    text = (REPO_ROOT / "docs/ATTESTATION_INTEROP.md").read_text(encoding="utf-8")
    stale = re.findall(r'"dorianVersion":\s*"\d[^"]*"', text)
    assert not stale, f"hardcoded dorianVersion in attestation-interop example: {stale}"
