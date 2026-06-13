"""Performance smoke budgets — coarse guards against gross regressions and hangs,
not microbenchmarks. Budgets are deliberately generous so they only fire on a
real problem (e.g. an accidental O(n^2) or an infinite loop), not CI noise.
"""

from __future__ import annotations

import contextlib
import io
import json
import time
from pathlib import Path

from dorian import cli


def _verify(repo: Path, claims: list[dict]) -> tuple[int, float]:
    cp = repo / "claims.json"
    cp.write_text(json.dumps({"claims": claims}), encoding="utf-8")
    buf = io.StringIO()
    t = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--repo", str(repo), "verify", "docs/design.md", "--claims", str(cp)])
    return rc, time.perf_counter() - t


def _c3(cid: str) -> dict:
    return {
        "id": cid,
        "text": "x",
        "kind": "reference",
        "load_bearing": True,
        "checkers": [{"type": "C3", "program": "string:src/routes.py::/v1/login"}],
    }


def test_verify_small_within_budget(fixture_repo: Path) -> None:
    rc, dt = _verify(fixture_repo, [_c3("c1")])
    assert rc == 0
    assert dt < 15.0, f"verify of 1 claim took {dt:.2f}s (budget 15s) — perf regression?"


def test_verify_100_claims_scaling_smoke(fixture_repo: Path) -> None:
    rc, dt = _verify(fixture_repo, [_c3(f"c{i}") for i in range(100)])
    assert rc == 0
    assert dt < 30.0, f"verify of 100 claims took {dt:.2f}s (budget 30s) — superlinear scaling?"


def test_revalidate_within_budget(fixture_repo: Path) -> None:
    rc, _ = _verify(fixture_repo, [_c3("c1")])
    assert rc == 0
    routes = fixture_repo / "src/routes.py"
    routes.write_text(routes.read_text().replace('"/v1/login": "auth.login",\n', ""))
    buf = io.StringIO()
    t = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["--repo", str(fixture_repo), "revalidate", "--since", "HEAD"])
    dt = time.perf_counter() - t
    assert rc == 4
    assert dt < 15.0, f"revalidate took {dt:.2f}s (budget 15s) — perf regression?"
