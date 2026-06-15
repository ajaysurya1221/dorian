"""Checker contract: read-only programs that re-validate a single claim.

Verdict semantics (load-bearing for H2 metric integrity):
- PASS: the claim is still supported.
- FAIL: the claim is no longer supported (drift in meaning, reference, or data).
- ERROR: the checker itself could not run (timeout, missing tool, engine failure).
  ERROR must NEVER be treated as BROKEN.
"""

from __future__ import annotations

import enum
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dorian.model import Claim, ReadSetEntry
from dorian.policy import ExecutionPolicy


class Verdict(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    verdict: Verdict
    detail: str = ""
    relocated: bool = False  # C1: span found at a new location (not an alarm)


@dataclass
class CheckContext:
    repo: Path
    claim: Claim
    supports: list[ReadSetEntry] = field(default_factory=list)
    rename_map: dict[str, str] = field(default_factory=dict)  # old path -> new path
    timeout_s: int = 30
    enable_c2lite: bool = False  # difflib contingency (flag-gated)
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)  # executable-checker gate


def resolve_path(ctx: CheckContext, uri: str) -> Path:
    """Resolve a repo-relative uri through the rename map to a working-tree path."""
    return ctx.repo / ctx.rename_map.get(uri, uri)


_SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL")


def run_readonly(
    cmd: str | list[str], cwd: Path, timeout_s: int, *, shell: bool = False
) -> tuple[int | None, str, str]:
    """Run a checker subprocess with stripped env and a hard timeout.

    Returns (returncode, stdout, stderr); returncode None means timeout/spawn
    failure — callers must map that to Verdict.ERROR, never FAIL.
    """
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def run_checker(ctx: CheckContext, spec_index: int) -> CheckResult:
    """Dispatch a claim's checker by CheckerSpec.type. Registered lazily to keep
    base import-light; checker modules register themselves on import."""
    from dorian.checkers import registry  # local import to avoid cycles

    spec = ctx.claim.checkers[spec_index]
    blocked = ctx.policy.block_reason(spec)
    if blocked is not None:
        # fail closed: a checker refused permission to run has proven nothing.
        # ERROR (never PASS/FAIL) means seal refuses and revalidate folds to
        # ERRORED — a blocked load-bearing claim is never silently green.
        return CheckResult(Verdict.ERROR, detail=blocked)
    impl = registry.get(spec.type)
    if impl is None:
        return CheckResult(Verdict.ERROR, detail=f"no checker registered for {spec.type}")
    try:
        return impl(ctx, spec)
    except Exception as exc:  # checker bugs are infra failures, not claim failures
        return CheckResult(Verdict.ERROR, detail=f"checker crashed: {type(exc).__name__}: {exc}")
