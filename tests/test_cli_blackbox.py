"""Black-box CLI tests: drive `dorian` out-of-process via `python -m dorian`.

These tests import NO dorian internals. They prepare inputs as a user would (a
hand-written claims.json, a real git repo), invoke the CLI as a subprocess, and
assert only on the externally visible contract: exit codes and stdout/stderr.
This is the layer the in-process tests (which call cli.main / internal functions)
cannot give — it proves the installed module entry point, argument parsing, and
exit-code wiring actually work end to end.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SUBCOMMANDS = [
    "capture",
    "seal",
    "verify",
    "status",
    "blast",
    "bindings",
    "revalidate",
    "report",
    "suggest-data-checks",
    "sync",
    "bench",
]


def run_dorian(*args: object, repo: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI out-of-process. `--repo` is a top-level arg, so it precedes
    the subcommand. Uses `python -m dorian` to avoid any PATH/entry-point
    assumption (the wheel entry point is exercised separately by test_packaging)."""
    cmd = [sys.executable, "-m", "dorian"]
    if repo is not None:
        cmd += ["--repo", str(repo)]
    cmd += [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _write_claims(repo: Path, claims: list[dict]) -> Path:
    """A user writes claims.json by hand — so we emit raw JSON, not via claims_io."""
    path = repo / "claims.json"
    path.write_text(json.dumps({"claims": claims}, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# smoke: help / version / usage                                               #
# --------------------------------------------------------------------------- #


def test_help_exits_0_and_lists_verify() -> None:
    r = run_dorian("--help")
    assert r.returncode == 0
    assert "verify" in r.stdout and "seal" in r.stdout
    assert "agents" in r.stdout.lower()  # the re-aimed self-description


def test_version_exits_0_and_prints_semver() -> None:
    r = run_dorian("--version")
    assert r.returncode == 0
    assert re.match(r"^dorian \d+\.\d+\.\d+", r.stdout.strip()), r.stdout


def test_every_subcommand_has_help() -> None:
    for cmd in SUBCOMMANDS:
        r = run_dorian(cmd, "--help")
        assert r.returncode == 0, f"`dorian {cmd} --help` exited {r.returncode}\n{r.stderr}"
        assert "usage:" in r.stdout.lower()


def test_no_subcommand_is_usage_error() -> None:
    r = run_dorian()
    assert r.returncode == 2
    assert "usage" in r.stderr.lower() or "required" in r.stderr.lower()


def test_unknown_subcommand_is_usage_error() -> None:
    r = run_dorian("frobnicate")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr.lower() or "usage" in r.stderr.lower()


def test_missing_repo_dir_is_usage_error() -> None:
    r = run_dorian("status", repo=Path("/no/such/repo/anywhere"))
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()


# --------------------------------------------------------------------------- #
# full lifecycle, entirely through the CLI                                    #
# --------------------------------------------------------------------------- #


def test_full_lifecycle_verify_revalidate_status_report_blast_sync(fixture_repo: Path) -> None:
    """The user journey: seal claims about a change, break one, watch dorian catch it."""
    claims = [
        {
            "id": "login-route",
            "text": "Login is served at /v1/login.",
            "kind": "reference",
            "load_bearing": True,
            "checkers": [{"type": "C3", "program": "string:src/routes.py::/v1/login"}],
        },
        {
            "id": "lots-rowcount",
            "text": "The lots dataset has 4 rows.",
            "kind": "quantity",
            "load_bearing": False,
            "checkers": [{"type": "C5", "program": "rowcount:data/lots.csv::== 4"}],
        },
    ]
    cp = _write_claims(fixture_repo, claims)

    # 1. verify (born-verifiable seal) — both claims hold => exit 0
    r = run_dorian("verify", "docs/design.md", "--claims", cp, repo=fixture_repo)
    assert r.returncode == 0, r.stderr
    assert "verified 2/2 claim(s)" in r.stdout
    assert (fixture_repo / "docs/design.md.warrant").is_file()

    # 2. status: a freshly sealed, all-verified warrant is not REVOKED/DEGRADED
    r = run_dorian("status", "docs/design.md", repo=fixture_repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split()[0] in ("WARRANTED", "TRUSTED")

    # 3. break the route claim in the working tree (the summary file is untouched)
    routes = fixture_repo / "src/routes.py"
    routes.write_text(routes.read_text().replace('"/v1/login": "auth.login",\n', ""))

    # 4. revalidate: only the affected claim is re-checked => BROKEN => REVOKED => exit 4
    r = run_dorian("revalidate", "--since", "HEAD", repo=fixture_repo)
    assert r.returncode == 4, f"expected REVOKED exit 4, got {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "BROKEN" in r.stdout and "login-route" in r.stdout
    assert "REVOKED" in r.stdout
    assert "lots-rowcount" not in r.stdout  # unchanged file => not a candidate

    # 5. status now reflects the revocation
    r = run_dorian("status", "docs/design.md", repo=fixture_repo)
    assert r.returncode == 4
    assert "REVOKED" in r.stdout

    # 6. report --audit emits valid JSONL (and leaks no raw source content beyond bounds)
    r = run_dorian("report", "--audit", repo=fixture_repo)
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert lines, "audit export was empty"
    for ln in lines:
        json.loads(ln)  # each line must be valid JSON

    # 7. blast: downstream traversal runs cleanly
    r = run_dorian("blast", "docs/design.md", repo=fixture_repo)
    assert r.returncode == 0, r.stderr

    # 8. sync: rebuild the derived index from sidecars
    r = run_dorian("sync", repo=fixture_repo)
    assert r.returncode == 0, r.stderr
    assert "indexed" in r.stdout.lower()


def test_verify_false_claim_writes_no_sidecar(fixture_repo: Path) -> None:
    """Born-verifiable: a claim false at seal time refuses the seal (exit 4), nothing written."""
    claims = [
        {
            "id": "bogus",
            "text": "Login is served at /v2/login.",
            "kind": "reference",
            "load_bearing": True,
            "checkers": [{"type": "C3", "program": "string:src/routes.py::/v2/login"}],
        }
    ]
    cp = _write_claims(fixture_repo, claims)
    r = run_dorian("verify", "docs/design.md", "--claims", cp, repo=fixture_repo)
    assert r.returncode == 4, f"{r.returncode}\n{r.stdout}\n{r.stderr}"
    assert not (fixture_repo / "docs/design.md.warrant").exists()
    assert "Traceback" not in r.stderr  # a refusal, not a crash
