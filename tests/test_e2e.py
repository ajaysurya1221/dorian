"""THE KERNEL PROOF: the full warrant lifecycle on the fixture repo.

Mirrors the v0.0 plan exactly:
1. capture the four sources docs/design.md was written from
2. seal docs/design.md with its 4 claims (C1 auth span LB, C5 shell TIMEOUT LB,
   C3 string /v1/login, C5 rowcount lots == 4); trusted via the status path
3. the canonical 3-change commit (rename auth, tune timeout, drop login) =>
   revalidate: auth claim VERIFIED with relocated detail; timeout claim BROKEN;
   login claim BROKEN; lots claim NOT a candidate; fold REVOKED; exit 4;
   events include claim.stale x3, claim.broken x2, fold.revoked
4. an unrelated commit => zero candidates, exit 0, no new claim/fold events
5. a tampered sidecar => IntegrityError propagates (sidecars are the truth)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import apply_three_change_commit, apply_unrelated_commit
from dorian import cli, commands, gitio, store
from dorian.capture.manual import parse_manual
from dorian.model import Anchor, CheckerSpec, Claim, IntegrityError
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

SPECS = ["src/auth.py:L4-7", "src/config.py:L1-1", "src/routes.py", "data/lots.csv"]

CLAIMS = [
    Claim(
        id="c1",
        text="Token verification lives in src/auth.py and uses RS256.",
        kind="fact",
        load_bearing=True,
        anchor=Anchor(3, 3, "uses RS256"),
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C1", program="rs-0"),),
    ),
    Claim(
        id="c2",
        text="The default request timeout is 30 seconds.",
        kind="quantity",
        load_bearing=True,
        supports=("rs-1",),
        checkers=(
            CheckerSpec(
                type="C5",
                program='shell:grep -Eq "TIMEOUT *= *30" src/config.py',
                watch=("src/config.py",),
            ),
        ),
    ),
    Claim(
        id="c3",
        text="Login is served at /v1/login.",
        kind="reference",
        load_bearing=False,
        supports=("rs-2",),
        checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
    ),
    Claim(
        id="c4",
        text="The lots dataset has 4 rows.",
        kind="quantity",
        load_bearing=False,
        supports=("rs-3",),
        checkers=(CheckerSpec(type="C5", program="rowcount:data/lots.csv::== 4"),),
    ),
]


def _event_kinds(repo: Path) -> list[str]:
    conn = store.connect(repo)
    try:
        return [r["kind"] for r in conn.execute("SELECT kind FROM event ORDER BY seq")]
    finally:
        conn.close()


def test_kernel_e2e(fixture_repo: Path, capsys) -> None:
    # 1) manual capture of the four sources
    readset = parse_manual(SPECS, fixture_repo)
    assert [e.uri for e in readset.entries] == [
        "src/auth.py",
        "src/config.py",
        "src/routes.py",
        "data/lots.csv",
    ]

    # 2) seal docs/design.md with the 4 claims; trusted via the status path
    w = seal_artifact(fixture_repo, "docs/design.md", readset, CLAIMS)
    args = cli.build_parser().parse_args(["--repo", str(fixture_repo), "status", "docs/design.md"])
    assert commands.cmd_status(args) == 0
    out = capsys.readouterr().out
    assert "VERIFIED=4" in out
    # born WARRANTED (= trusted at birth); never DEGRADED/REVOKED before drift
    assert out.split()[0] in ("WARRANTED", "TRUSTED")

    # 3) the canonical 3-change commit, then incremental revalidation
    base = gitio.head_ref(fixture_repo)
    drift_sha = apply_three_change_commit(fixture_repo)
    res = revalidate(fixture_repo, since=base)

    assert res.candidates == 3  # lots.csv untouched => c4 is NOT a candidate
    all_lists = (res.broken, res.relocated, res.errored, res.passed)
    assert "c4" not in {cid for lst in all_lists for _, cid, _ in lst}

    assert [(wid, cid) for wid, cid, _ in res.relocated] == [(w.id, "c1")]
    assert all(detail for _, _, detail in res.relocated)  # relocated detail present
    assert {cid for _, cid, _ in res.broken} == {"c2", "c3"}
    assert res.errored == []
    assert res.passed == []
    assert res.folds[w.id][1] == "REVOKED"
    assert res.exit_code == 4

    conn = store.connect(fixture_repo)
    try:
        states = {s["claim_id"]: s["state"] for s in store.get_claim_states(conn, w.id)}
        trust = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()[
            "trust_state"
        ]
    finally:
        conn.close()
    assert states == {"c1": "VERIFIED", "c2": "BROKEN", "c3": "BROKEN", "c4": "VERIFIED"}
    assert trust == "REVOKED"

    kinds = _event_kinds(fixture_repo)
    assert kinds.count("claim.stale") == 3
    assert kinds.count("claim.broken") == 2
    assert kinds.count("fold.revoked") == 1

    # 4) an unrelated commit produces zero candidates and zero alarms
    n_alarm_events = sum(1 for k in kinds if k.startswith(("claim.", "fold.")))
    apply_unrelated_commit(fixture_repo)
    res2 = revalidate(fixture_repo, since=drift_sha)
    assert res2.candidates == 0
    assert res2.exit_code == 0
    assert res2.folds == {}
    kinds2 = _event_kinds(fixture_repo)
    assert sum(1 for k in kinds2 if k.startswith(("claim.", "fold."))) == n_alarm_events

    # 5) tampering the sidecar is detected: sidecars are the source of truth
    sidecar = fixture_repo / "docs/design.md.warrant"
    d = json.loads(sidecar.read_text())
    d["warrant"]["claims"][1]["text"] = "The default request timeout is 10 seconds."
    sidecar.write_text(json.dumps(d))
    with pytest.raises(IntegrityError):
        revalidate(fixture_repo, since=drift_sha)
