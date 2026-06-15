"""C3 `regex:` ReDoS backstop: a catastrophic pattern is killed by a timeout.

The match runs in a spawned worker process so a wall-clock timeout can actually
stop it — a thread or in-process signal cannot interrupt a C-level re.search().
These tests pin: safe patterns still PASS/FAIL in-band; a pathological pattern
ERRORs with `regex_timeout` and returns within a bounded wall-clock window
(proving it was killed, not merely slow); and the result is distinct from an
ordinary no-match FAIL.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from dorian.checkers.base import CheckContext, Verdict
from dorian.checkers.c3_ref import check
from dorian.model import CheckerSpec, Claim

# every case spawns a worker process (the catastrophic case runs to the timeout
# bound), so this module belongs in the slow lane like the C4 subprocess tests
pytestmark = pytest.mark.slow


def _run(repo: Path, program: str, timeout_s: int = 2):
    spec = CheckerSpec(type="C3", program=program, timeout_s=timeout_s)
    claim = Claim(id="c", text="x", kind="reference", load_bearing=False, checkers=(spec,))
    return check(CheckContext(repo=repo, claim=claim), spec)


def _repo(tmp_path: Path) -> Path:
    # a benign matchable line + a long non-matching 'a' run that makes (a+)+ blow up
    (tmp_path / "f.py").write_text("TIMEOUT = 30\n" + ("a" * 50) + "b\n", encoding="utf-8")
    return tmp_path


def test_safe_regex_still_matches(tmp_path: Path) -> None:
    assert _run(_repo(tmp_path), r"regex:f.py::TIMEOUT\s*=\s*30").verdict is Verdict.PASS


def test_safe_regex_no_match_fails_cleanly(tmp_path: Path) -> None:
    res = _run(_repo(tmp_path), "regex:f.py::DOES_NOT_OCCUR")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "regex_missing"  # ordinary no-match, distinct from a timeout


def test_catastrophic_regex_times_out_quickly(tmp_path: Path) -> None:
    start = time.monotonic()
    res = _run(_repo(tmp_path), r"regex:f.py::(a+)+$", timeout_s=2)
    elapsed = time.monotonic() - start
    assert res.verdict is Verdict.ERROR  # never a silent stall, never PASS/FAIL
    assert "regex_timeout" in res.detail
    # killed near the bound, not run to (effectively unbounded) completion. Generous
    # ceiling absorbs spawn + SIGTERM grace + CI jitter while still proving the kill.
    assert elapsed < 15, f"timeout did not bound the match: {elapsed:.1f}s"
