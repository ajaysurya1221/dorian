"""`dorian claude-code install-claim-warrants`: scaffold the Claude Code skill.

Installs a project-local Claude Code **skill** (and an opt-in, reminder-only Stop
hook) that drafts Dorian *claim warrants* for the checkable facts in a coding
agent's change summary. The skill only DRAFTS; ``dorian verify`` proves the claims
deterministically and token-free — no model runs at check time.

Like ``dorian init``, this module writes files only. It never runs a checker, never
executes code, never writes outside the target repo root, and never overwrites an
existing file without ``--force`` (re-running is idempotent). Template content is
shipped as package data under ``dorian/templates/claude_code/`` and copied verbatim,
so it works from an installed wheel, not just an editable checkout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

# Logical groups a caller can select. "skill" and "settings" install by default;
# "hook" is opt-in (--with-hook). --settings-only selects {"settings"} alone.
GROUPS = ("skill", "settings", "hook")
DEFAULT_GROUPS = frozenset({"skill", "settings"})

SKILL_DIR = ".claude/skills/dorian-claim-warrants"
HOOK_PATH = ".claude/hooks/dorian_claim_warrants_stop.py"


@dataclass(frozen=True)
class _Template:
    """One template file: package-relative source, repo-relative dest, group, blurb."""

    src: str  # relative to dorian/templates/claude_code/
    dest: str  # repo-relative posix path
    group: str  # skill | settings | hook
    blurb: str


# The authoritative install manifest. Every `src` must exist in package data
# (asserted by tests); `dest` is where it lands in the target repo. Deterministic
# order — no directory walking, no surprise files.
MANIFEST: tuple[_Template, ...] = (
    _Template(
        "dorian-claim-warrants/SKILL.md",
        f"{SKILL_DIR}/SKILL.md",
        "skill",
        "the skill, invoked as /dorian-claim-warrants",
    ),
    _Template(
        "dorian-claim-warrants/README.md",
        f"{SKILL_DIR}/README.md",
        "skill",
        "what the bundle is and how to use it",
    ),
    _Template(
        "dorian-claim-warrants/examples/good-claims.json",
        f"{SKILL_DIR}/examples/good-claims.json",
        "skill",
        "a worked set of strong claims",
    ),
    _Template(
        "dorian-claim-warrants/examples/bad-claims.md",
        f"{SKILL_DIR}/examples/bad-claims.md",
        "skill",
        "claims to leave as prose, and why",
    ),
    _Template(
        "dorian-claim-warrants/examples/final-message-example.md",
        f"{SKILL_DIR}/examples/final-message-example.md",
        "skill",
        "a summary turned into claim warrants",
    ),
    _Template(
        "dorian-claim-warrants/templates/change-note.md",
        f"{SKILL_DIR}/templates/change-note.md",
        "skill",
        "change-note skeleton the skill fills in",
    ),
    _Template(
        "dorian-claim-warrants/templates/claims.json",
        f"{SKILL_DIR}/templates/claims.json",
        "skill",
        "claims.json skeleton",
    ),
    _Template(
        "dorian-claim-warrants/reference/checker-selection.md",
        f"{SKILL_DIR}/reference/checker-selection.md",
        "skill",
        "match the checker to the claim",
    ),
    _Template(
        "dorian-claim-warrants/reference/safety-boundary.md",
        f"{SKILL_DIR}/reference/safety-boundary.md",
        "skill",
        "model drafts, Dorian proves; not a sandbox",
    ),
    _Template(
        "settings/settings.dorian-claim-warrants.review-first.example.json",
        ".claude/settings.dorian-claim-warrants.review-first.example.json",
        "settings",
        "review-first permissions example (default)",
    ),
    _Template(
        "settings/settings.dorian-claim-warrants.trusted-local.example.json",
        ".claude/settings.dorian-claim-warrants.trusted-local.example.json",
        "settings",
        "trusted-local permissions example (opt-in)",
    ),
    _Template(
        "hooks/dorian_claim_warrants_stop.py",
        HOOK_PATH,
        "hook",
        "opt-in, reminder-only Stop hook (not auto-enabled)",
    ),
)

NEXT_STEPS = (
    "Restart Claude Code (a new skills directory registers only at startup)",
    "After a coding change, invoke:  /dorian-claim-warrants",
    "Review the drafted docs/changes/<slug>.md and .claims.json",
    "Prove them:  dorian verify docs/changes/<slug>.md --claims"
    " docs/changes/<slug>.claims.json --strength-gate=fail --binding-gate=warn",
    "Commit the sealed .warrant alongside your change",
    "On later PRs the Action runs `dorian revalidate` and REVOKEs a broken claim",
)

TRUST_BOUNDARY = (
    "The skill drafts claims. Dorian verifies deterministically, token-free. "
    "C4 pytest:/C5 shell: checkers can execute code — use trusted repos."
)


@dataclass(frozen=True)
class ScaffoldFile:
    """One planned write: repo-relative path, content, blurb, group, prior existence."""

    path: str
    content: str
    blurb: str
    group: str
    exists: bool


@dataclass(frozen=True)
class ScaffoldPlan:
    repo_root: Path
    files: tuple[ScaffoldFile, ...]
    is_git: bool


@dataclass(frozen=True)
class ApplyResult:
    created: tuple[str, ...]
    overwritten: tuple[str, ...]
    skipped: tuple[str, ...]
    warnings: tuple[str, ...]


def find_repo_root(start: Path) -> tuple[Path, bool]:
    """Repo root for ``start``: the nearest ancestor containing ``.git`` (file or
    dir), else ``start`` resolved. Returns ``(root, is_git)``. Never raises."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d, True
    return start, False


def _read_template(src: str) -> str:
    """Read a template file from package data (works from wheel or editable)."""
    node = files("dorian")
    for part in ("templates", "claude_code", *src.split("/")):
        node = node.joinpath(part)
    return node.read_text(encoding="utf-8")


def _ensure_within(repo: Path, target: Path) -> None:
    """Defense in depth: refuse to write anywhere outside the repo root."""
    resolved = (target if target.is_absolute() else repo / target).resolve()
    if not resolved.is_relative_to(repo):
        raise ValueError(f"refusing to write outside repo: {target}")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # per-process: no shared-.tmp race
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def build_plan(
    repo: Path,
    *,
    groups: frozenset[str] = DEFAULT_GROUPS,
    manifest: tuple[_Template, ...] = MANIFEST,
) -> ScaffoldPlan:
    """Compute (without writing) the files the install would scaffold for ``repo``.

    ``groups`` selects which manifest groups to install (subset of ``GROUPS``).
    ``manifest`` defaults to the claim-warrants MANIFEST; a sibling installer (e.g.
    ``dorian loop install``) passes its own manifest of the same ``_Template`` shape.
    ``repo`` should already be the repo root (see ``find_repo_root``)."""
    root, is_git = find_repo_root(repo)
    selected = [t for t in manifest if t.group in groups]
    files_ = tuple(
        ScaffoldFile(
            path=t.dest,
            content=_read_template(t.src),
            blurb=t.blurb,
            group=t.group,
            exists=(root / t.dest).exists(),
        )
        for t in selected
    )
    return ScaffoldPlan(repo_root=root, files=files_, is_git=is_git)


def apply(plan: ScaffoldPlan, *, force: bool, dry_run: bool) -> ApplyResult:
    """Realize the plan. Existing files are skipped unless ``force``; with
    ``dry_run`` nothing is written but the same classification is returned."""
    created: list[str] = []
    overwritten: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    if not plan.is_git:
        warnings.append(
            "target is not a git repository — Dorian is git-native; "
            "run `git init` so warrants and revalidation work"
        )
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
        warnings=tuple(warnings),
    )
