"""C4 test-binding checker: does the bound pytest test still exist and pass?

Program grammar:
    pytest:<nodeid>      e.g. pytest:tests/test_auth.py::test_rs256

The nodeid's file part resolves through ctx.rename_map (a renamed test file is
not 'gone') and must stay inside the repo (same containment guard as C1/C3/C5).
The test runs as `python -m pytest <nodeid>` — the PATH interpreter, so the
repo's active environment resolves — with a stripped env, cwd=ctx.repo and the
spec's timeout. Exit-code mapping:
    0 -> PASS
    1 -> FAIL test_failing       (the test ran and is red)
    4 -> FAIL test_gone ONLY on the nodeid-gone stderr signatures
         ("ERROR: file or directory not found" / "ERROR: not found:");
         any other exit 4 is ERROR — pytest exits 4 (UsageError) for pure
         infrastructure too (broken conftest, bad ini/plugin, unimportable
         nodeid-targeted file: "ERROR: found no collectors"), and infra must
         never look like staleness
    5 -> FAIL test_gone          (nothing collected: the nodeid is gone)
    2/3, timeout, spawn failure -> ERROR.
Exit 1 has one infra impostor: a PATH `python` whose environment lacks pytest
also exits 1, with an empty stdout and runpy's "No module named pytest" on
stderr (a real pytest exit 1 always prints a session summary on stdout). That
signature maps to ERROR pytest_missing, never FAIL.
"""

from __future__ import annotations

import os
import subprocess

from dorian.checkers import registry
from dorian.checkers.base import _SAFE_ENV_KEYS, CheckContext, CheckResult, Verdict
from dorian.model import CheckerSpec

_PYTEST_ARGS = ("-q", "--no-header", "-x", "-p", "no:cacheprovider")


def check(ctx: CheckContext, spec: CheckerSpec) -> CheckResult:
    prefix, sep, nodeid = spec.program.partition(":")
    nodeid = nodeid.strip()
    if prefix != "pytest" or not sep or not nodeid:
        return CheckResult(Verdict.ERROR, detail="bad_program")

    file, sep, rest = nodeid.partition("::")
    file = ctx.rename_map.get(file, file)
    if not file or not (ctx.repo / file).resolve().is_relative_to(ctx.repo.resolve()):
        # a hostile nodeid ('..' or absolute) must not probe files outside the repo
        return CheckResult(Verdict.ERROR, detail="bad_program")
    nodeid = file + sep + rest

    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", nodeid, *_PYTEST_ARGS],
            cwd=ctx.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=spec.timeout_s,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        # timeout or missing interpreter/pytest: infrastructure, never FAIL
        return CheckResult(Verdict.ERROR, detail=f"pytest did not complete: {type(exc).__name__}")
    if proc.returncode == 0:
        return CheckResult(Verdict.PASS)
    if proc.returncode == 1:
        if not proc.stdout.strip() and "No module named pytest" in proc.stderr:
            # `python -m pytest` without pytest installed: infra, not a red test
            return CheckResult(Verdict.ERROR, detail="pytest_missing")
        return CheckResult(Verdict.FAIL, detail="test_failing")
    if proc.returncode == 4:
        # exit 4 (UsageError) is ambiguous: a vanished nodeid AND pure infra
        # (broken conftest, bad ini/plugin, unimportable target file) both land
        # here. Only the nodeid-gone stderr signatures are staleness (probed
        # against pytest 9.0.3); everything else is ERROR, never FAIL.
        if "ERROR: file or directory not found" in proc.stderr or (
            "ERROR: not found:" in proc.stderr
        ):
            return CheckResult(Verdict.FAIL, detail="test_gone")
        return CheckResult(Verdict.ERROR, detail="pytest_error: exit 4 (usage/collection error)")
    if proc.returncode == 5:  # no tests collected: the nodeid is gone
        return CheckResult(Verdict.FAIL, detail="test_gone")
    # 2 (interrupted, e.g. whole-file collection error), 3 (internal error), unknown
    return CheckResult(Verdict.ERROR, detail=f"pytest_error: exit {proc.returncode}")


registry.register("C4", check)
