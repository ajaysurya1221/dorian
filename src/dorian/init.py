"""`dorian init`: first-run scaffolding for the golden path.

Writes three files so a first-time user reaches a sealed warrant in minutes:

- ``claims.json`` — a *born-verifiable* starter claim (so the very first
  ``dorian verify`` seals green, not red);
- ``dorian-change-note.md`` — the change note those claims back;
- ``.github/workflows/dorian.yml`` — a GitHub Action that re-checks the sealed
  claims on every pull request.

This module writes files only. It never runs a checker, never executes code,
never writes outside the repo root, and never overwrites an existing file
without ``--force`` (re-running is safe and idempotent). The starter claim is a
read-only C3 family (``config-value:`` when a ``pyproject.toml`` package name is
available, else ``path:``) — never an executable C4/C5 checker — so init is
safe by default.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dorian import __version__

CLAIMS_FILE = "claims.json"
NOTE_FILE = "dorian-change-note.md"
WORKFLOW_FILE = ".github/workflows/dorian.yml"

# Files init will bind a `path:` existence claim to when no pyproject name is
# available, in preference order. The first one that exists wins.
_PATH_CANDIDATES = (
    "README.md",
    "README.rst",
    "README",
    "LICENSE",
    "LICENSE.md",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
)

NEXT_STEPS = (
    f"Review {CLAIMS_FILE} and {NOTE_FILE}",
    f"Seal them:  dorian verify {NOTE_FILE} --claims {CLAIMS_FILE}",
    f"Commit {NOTE_FILE}.warrant alongside your change",
    "Add code claims:  dorian suggest-claims <your_module.py>",
    "Open a PR — the workflow re-checks every sealed claim on every change",
)


@dataclass(frozen=True)
class InitFile:
    """One scaffolded file: its repo-relative posix path, the content to write,
    a one-line summary blurb, and whether it already exists at plan time."""

    path: str
    content: str
    blurb: str
    exists: bool


@dataclass(frozen=True)
class InitPlan:
    repo_root: Path
    files: tuple[InitFile, ...]
    starter_desc: str


@dataclass(frozen=True)
class ApplyResult:
    created: tuple[str, ...]
    overwritten: tuple[str, ...]
    skipped: tuple[str, ...]
    warnings: tuple[str, ...]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "file"


def _project_name(repo: Path) -> str | None:
    """The ``project.name`` from ``pyproject.toml`` if cleanly parseable, else None."""
    pp = repo / "pyproject.toml"
    if not pp.is_file():
        return None
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    name = data.get("project", {}).get("name") if isinstance(data.get("project"), dict) else None
    return name if isinstance(name, str) and name else None


def _starter(repo: Path) -> tuple[dict, str, str]:
    """Choose a born-verifiable starter claim grounded in this repo's current
    state. Returns (claim_dict, note_fact_line, one_line_desc).

    Preference: a ``config-value:`` claim about the pyproject package name (the
    flagship checker — the family that caught httpx#3592), falling back to a
    ``path:`` existence claim about a file that is present. Both are read-only.
    """
    name = _project_name(repo)
    if name is not None:
        program = f"config-value:pyproject.toml:project.name:{json.dumps(name)}"
        claim = {
            "id": "package-name",
            "text": f'The package name declared in pyproject.toml is "{name}".',
            "kind": "fact",
            "load_bearing": False,
            "checkers": [{"type": "C3", "program": program}],
        }
        fact = f"The package name declared in `pyproject.toml` (`project.name`) is `{name}`."
        return claim, fact, f"config-value: pyproject.toml project.name == {name!r}"

    rel = next((c for c in _PATH_CANDIDATES if (repo / c).is_file()), NOTE_FILE)
    claim = {
        "id": f"{_slug(Path(rel).stem)}-present",
        "text": f"The file {rel} is present.",
        "kind": "fact",
        "load_bearing": False,
        "checkers": [{"type": "C3", "program": f"path:{rel}"}],
    }
    return claim, f"The file `{rel}` is present.", f"path: {rel} exists"


def _claims_content(claim: dict) -> str:
    # indent=2, fixed field order (built deterministically); no sort_keys so the
    # human-friendly id/text/kind order is preserved in the scaffolded file.
    return json.dumps({"claims": [claim]}, indent=2) + "\n"


def _note_content(fact: str) -> str:
    return (
        "# Dorian change note\n"
        "\n"
        "This note records the load-bearing facts this change relies on. `dorian verify`\n"
        "seals them into a `.warrant` sidecar and `dorian` re-checks them on every future\n"
        "pull request, so a later change that quietly breaks one of these promises fails\n"
        "CI instead of shipping silently.\n"
        "\n"
        f"- {fact}\n"
        "\n"
        f"The checkable claims behind this note live in `{CLAIMS_FILE}`. Seal them with:\n"
        "\n"
        f"    dorian verify {NOTE_FILE} --claims {CLAIMS_FILE}\n"
        "\n"
        "Then replace the example above with the real facts your change depends on, and\n"
        "add more checks with `dorian suggest-claims <your_module.py>`.\n"
    )


def _workflow_content() -> str:
    # Pin the action to THIS package's version so a `pip install dorian-vwp`
    # and the workflow always agree. The snippet mirrors action/README.md.
    return (
        "name: dorian\n"
        "on: [pull_request]\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "  pull-requests: write   # sticky comment (update-or-create)\n"
        "\n"
        "jobs:\n"
        "  revalidate:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v6\n"
        "        with:\n"
        "          fetch-depth: 0   # required: revalidate diffs against the PR base sha\n"
        "          persist-credentials: false\n"
        f"      - uses: ajaysurya1221/dorian/action@v{__version__}\n"
        "        with:\n"
        "          fail_on: revoked\n"
    )


def build_plan(repo: Path) -> InitPlan:
    """Compute (without writing) the files init would scaffold for ``repo``."""
    claim, fact, desc = _starter(repo)
    specs = (
        (CLAIMS_FILE, _claims_content(claim), desc),
        (NOTE_FILE, _note_content(fact), "the change note these claims back"),
        (WORKFLOW_FILE, _workflow_content(), "re-checks claims on every pull request"),
    )
    files = tuple(
        InitFile(path=path, content=content, blurb=blurb, exists=(repo / path).exists())
        for path, content, blurb in specs
    )
    return InitPlan(repo_root=repo.resolve(), files=files, starter_desc=desc)


def _ensure_within(repo: Path, target: Path) -> None:
    """Defense in depth: refuse to write anywhere outside the repo root."""
    resolved = (target if target.is_absolute() else repo / target).resolve()
    if not resolved.is_relative_to(repo):
        raise ValueError(f"refusing to write outside repo: {target}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def apply(plan: InitPlan, *, force: bool, dry_run: bool) -> ApplyResult:
    """Realize the plan. Existing files are skipped unless ``force``. With
    ``dry_run`` nothing is written but the same classification is returned."""
    created: list[str] = []
    overwritten: list[str] = []
    skipped: list[str] = []
    for f in plan.files:
        target = plan.repo_root / f.path
        _ensure_within(plan.repo_root, target)
        if f.exists and not force:
            skipped.append(f.path)
            continue
        if not dry_run:
            _atomic_write(target, f.content)
        (overwritten if f.exists else created).append(f.path)
    return ApplyResult(
        created=tuple(created),
        overwritten=tuple(overwritten),
        skipped=tuple(skipped),
        warnings=(),
    )
