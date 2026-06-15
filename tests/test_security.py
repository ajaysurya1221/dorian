"""Security regression tests.

These pin the boundaries an attacker (or a buggy/poisoned agent-emitted
claims.json) would probe: path traversal out of the repo, ReDoS via an
unbounded regex, environment leakage into executed checkers, and source-content
carryover in the audit export. They are all safe and local (no network, no real
secrets, no destructive ops). Scope-lint exit-6 enforcement is covered in
test_verify.py::test_verify_restricted_readset_is_exit_6_then_allow; the static
checker path-escape matrix is covered in test_c3.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dorian import cli, store
from dorian.checkers.base import CheckContext, Verdict, run_checker, run_readonly
from dorian.model import CheckerSpec, Claim


def _run_c3(repo: Path, program: str):
    claim = Claim(
        id="c",
        text="x",
        kind="reference",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program=program),),
    )
    return run_checker(CheckContext(repo=repo, claim=claim), 0)


def test_verify_path_traversal_is_blocked_and_reads_nothing(fixture_repo: Path, capsys) -> None:
    """A claim whose program escapes the repo must be refused without reading the target."""
    claims = {
        "claims": [
            {
                "id": "evil",
                "text": "read /etc/passwd",
                "kind": "fact",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "path:../../../../../../etc/passwd"}],
            }
        ]
    }
    cp = fixture_repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")

    rc = cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)])
    err = capsys.readouterr().err
    assert rc == 2  # refused at read-set capture, before any checker runs
    assert "outside" in err.lower()
    assert "root:" not in err  # never echoed /etc/passwd content
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_c3_symbol_traversal_is_error_not_pass(fixture_repo: Path) -> None:
    """Defense in depth: the checker rejects an out-of-repo file as ERROR, not PASS/FAIL."""
    res = _run_c3(fixture_repo, "symbol:../../../../etc/passwd::root")
    assert res.verdict is Verdict.ERROR


def test_c3_regex_over_length_cap_is_error_redos_guard(fixture_repo: Path) -> None:
    """The 500-char pattern cap is the ReDoS boundary: an over-long regex ERRORs, never runs."""
    over_long = "regex:src/auth.py::" + ("a" * 600)
    res = _run_c3(fixture_repo, over_long)
    assert res.verdict is Verdict.ERROR
    # a within-cap, well-anchored pattern still works (sanity)
    ok = _run_c3(fixture_repo, r"regex:src/auth.py::RS256")
    assert ok.verdict is Verdict.PASS


def test_c3_within_cap_catastrophic_regex_is_bounded_by_timeout(fixture_repo: Path) -> None:
    """The real ReDoS risk is backtracking WITHIN the 500-char cap. The match runs
    in a worker process killed at spec.timeout_s, so a pathological pattern ERRORs
    with regex_timeout instead of stalling — never a silent hang, never PASS/FAIL."""
    (fixture_repo / "evil.txt").write_text(("a" * 50) + "b\n", encoding="utf-8")
    claim = Claim(
        id="c",
        text="x",
        kind="reference",
        load_bearing=False,
        checkers=(CheckerSpec(type="C3", program=r"regex:evil.txt::(a+)+$", timeout_s=2),),
    )
    start = time.monotonic()
    res = run_checker(CheckContext(repo=fixture_repo, claim=claim), 0)
    assert res.verdict is Verdict.ERROR  # bounded: killed, not stalled or passed
    assert "regex_timeout" in res.detail
    assert time.monotonic() - start < 15, "regex timeout did not bound the match"


def test_checker_subprocess_env_is_stripped(fixture_repo: Path) -> None:
    """Executed checkers (C4/C5 shell) must not inherit arbitrary env (secrets, tokens)."""
    os.environ["DORIAN_TEST_SECRET"] = "leak-me-please"
    try:
        rc, out, _err = run_readonly(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('DORIAN_TEST_SECRET', 'ABSENT'))",
            ],
            fixture_repo,
            timeout_s=15,
        )
        assert rc == 0
        assert "leak-me-please" not in out
        assert "ABSENT" in out
    finally:
        os.environ.pop("DORIAN_TEST_SECRET", None)


def test_audit_export_truncates_detail_carryover(fixture_repo: Path) -> None:
    """report --audit bounds any 'detail' carryover to 160 chars (no full source/secret leak)."""
    secret_tail = "SECRET_TAIL_MUST_NOT_LEAK"
    long_detail = ("x" * 300) + secret_tail  # the tail sits well past the 160-char bound
    conn = store.connect(fixture_repo)
    try:
        store.append_event(
            conn,
            warrant_id="sha256:audit-redaction-probe",
            actor="test",
            kind="claim.broken",
            cause={"checker": "C5", "detail": long_detail},
        )
        conn.commit()
    finally:
        conn.close()

    lines = cli_audit(fixture_repo)
    blob = "\n".join(lines)
    assert blob, "audit export was empty"
    assert secret_tail not in blob, "detail carryover past the 160-char bound leaked"
    for ln in lines:
        cause = json.loads(ln).get("cause")
        if isinstance(cause, dict) and isinstance(cause.get("detail"), str):
            assert len(cause["detail"]) <= 160


def cli_audit(repo: Path) -> list[str]:
    """Capture `report --audit` JSONL via the public CLI (out-of-band of report.py internals)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--repo", str(repo), "report", "--audit"])
    assert rc == 0
    return [ln for ln in buf.getvalue().splitlines() if ln.strip()]
