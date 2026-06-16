"""TASK fold: trust fold + transition helpers (src/dorian/fold.py).

Acceptance matrix:
- table-driven fold() tests covering every rule, both revoke_on policies,
  UNBACKED/SUPERSEDED never affecting the fold, and UNBACKED-only => TRUSTED;
- permutation invariance (shuffled states give the same fold);
- apply_claim_state: no-op on same state (no event row), event with actor on change;
- apply_fold: WARRANTED -> TRUSTED -> REVOKED on a stored warrant, exactly one
  fold event per transition;
- KeyError on unknown warrant_id / claim_id in both apply helpers.
"""

from __future__ import annotations

import json
import random

import pytest

from dorian import store
from dorian.fold import apply_claim_state, apply_fold, fold
from dorian.model import CheckerSpec, Claim, FoldPolicy, ProducedBy, Warrant, sha256_hex

LB = FoldPolicy(revoke_on="load_bearing_broken")
AB = FoldPolicy(revoke_on="any_broken")

# (test_id, states=[(claim_state, load_bearing)], policy, expected_trust_state)
FOLD_MATRIX = [
    ("all_verified", [("VERIFIED", True), ("VERIFIED", False)], LB, "TRUSTED"),
    ("no_claims", [], LB, "TRUSTED"),
    ("unbacked_only", [("UNBACKED", True), ("UNBACKED", False)], LB, "TRUSTED"),
    ("superseded_only", [("SUPERSEDED", True)], LB, "TRUSTED"),
    ("proposed_falls_through", [("PROPOSED", True)], LB, "TRUSTED"),
    ("lb_broken_revokes", [("VERIFIED", False), ("BROKEN", True)], LB, "REVOKED"),
    ("mixed_broken_revokes", [("BROKEN", True), ("BROKEN", False)], LB, "REVOKED"),
    ("nonlb_broken_degrades", [("VERIFIED", True), ("BROKEN", False)], LB, "DEGRADED"),
    ("any_broken_nonlb_revokes", [("VERIFIED", True), ("BROKEN", False)], AB, "REVOKED"),
    ("any_broken_lb_revokes", [("BROKEN", True)], AB, "REVOKED"),
    ("errored_unknown", [("VERIFIED", True), ("ERRORED", False)], LB, "UNKNOWN"),
    ("errored_unknown_any_broken_policy", [("ERRORED", True)], AB, "UNKNOWN"),
    ("broken_beats_errored", [("ERRORED", True), ("BROKEN", False)], LB, "DEGRADED"),
    ("lb_broken_beats_errored", [("ERRORED", False), ("BROKEN", True)], LB, "REVOKED"),
    ("unbacked_never_affects", [("UNBACKED", True), ("ERRORED", False)], LB, "UNKNOWN"),
    ("superseded_never_affects", [("SUPERSEDED", True), ("BROKEN", False)], LB, "DEGRADED"),
    ("unbacked_plus_verified", [("UNBACKED", True), ("VERIFIED", False)], LB, "TRUSTED"),
]


@pytest.mark.parametrize(
    ("states", "policy", "expected"),
    [case[1:] for case in FOLD_MATRIX],
    ids=[case[0] for case in FOLD_MATRIX],
)
def test_fold_matrix(states, policy, expected):
    assert fold(states, policy) == expected


@pytest.mark.parametrize(
    ("states", "policy", "expected"),
    [case[1:] for case in FOLD_MATRIX],
    ids=[case[0] for case in FOLD_MATRIX],
)
def test_fold_permutation_invariance(states, policy, expected):
    rng = random.Random(0)
    for _ in range(5):
        shuffled = list(states)
        rng.shuffle(shuffled)
        assert fold(shuffled, policy) == expected


# --- stored-warrant transition helpers -----------------------------------------


def _warrant() -> Warrant:
    spec = CheckerSpec(type="C1", program="src/auth.py#L6-6", watch=("src/auth.py",))
    return Warrant.create(
        artifact_uri="docs/design.md",
        artifact_hash=sha256_hex(b"artifact"),
        git_ref="0" * 40,
        produced_by=ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z"),
        read_set=(),
        claims=(
            Claim(
                id="c-rs256",
                text="auth uses RS256",
                kind="fact",
                load_bearing=True,
                checkers=(spec,),
            ),
            Claim(
                id="c-timeout",
                text="timeout is 30s",
                kind="quantity",
                load_bearing=False,
                checkers=(spec,),
            ),
        ),
        fold_policy=FoldPolicy(),
        sealed_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def stored(tmp_path):
    conn = store.connect(tmp_path)
    w = _warrant()
    store.upsert_warrant(conn, w, "docs/design.md.warrant")
    conn.commit()
    yield conn, w
    conn.close()


def _events(conn, kind_prefix: str) -> list:
    return conn.execute(
        "SELECT * FROM event WHERE kind LIKE ? ORDER BY seq", (kind_prefix + "%",)
    ).fetchall()


def test_apply_claim_state_noop_on_same_state(stored):
    conn, w = stored
    # claims with checkers index as VERIFIED; re-applying VERIFIED is a no-op
    assert apply_claim_state(conn, w.id, "c-rs256", "VERIFIED", actor="tester", cause=None) is False
    assert _events(conn, "claim.") == []
    row = conn.execute(
        "SELECT state, state_changed_at FROM claim WHERE warrant_id = ? AND id = ?",
        (w.id, "c-rs256"),
    ).fetchone()
    assert row["state"] == "VERIFIED"
    assert row["state_changed_at"] is None


def test_apply_claim_state_change_emits_event_with_actor(stored):
    conn, w = stored
    changed = apply_claim_state(
        conn, w.id, "c-rs256", "BROKEN", actor="tester", cause={"reason": "span drift"}
    )
    assert changed is True
    row = conn.execute(
        "SELECT state, state_changed_at FROM claim WHERE warrant_id = ? AND id = ?",
        (w.id, "c-rs256"),
    ).fetchone()
    assert row["state"] == "BROKEN"
    assert row["state_changed_at"] is not None
    events = _events(conn, "claim.")
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "claim.broken"
    assert ev["actor"] == "tester"
    assert ev["claim_id"] == "c-rs256"
    assert ev["warrant_id"] == w.id
    assert json.loads(ev["cause"]) == {"reason": "span drift"}


def test_apply_claim_state_unknown_ids_raise(stored):
    conn, w = stored
    with pytest.raises(KeyError):
        apply_claim_state(conn, "no-such-warrant", "c-rs256", "BROKEN", actor="t", cause=None)
    with pytest.raises(KeyError):
        apply_claim_state(conn, w.id, "no-such-claim", "BROKEN", actor="t", cause=None)
    assert _events(conn, "claim.") == []


def test_apply_fold_unknown_warrant_raises(stored):
    conn, _ = stored
    with pytest.raises(KeyError):
        apply_fold(conn, "no-such-warrant", FoldPolicy(), actor="t")
    assert _events(conn, "fold.") == []


def test_apply_fold_warranted_to_trusted_to_revoked(stored):
    conn, w = stored
    policy = w.fold_policy

    # fresh index: WARRANTED, all claims VERIFIED -> TRUSTED
    assert apply_fold(conn, w.id, policy, actor="tester") == ("WARRANTED", "TRUSTED")
    row = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()
    assert row["trust_state"] == "TRUSTED"
    trusted_events = _events(conn, "fold.trusted")
    assert len(trusted_events) == 1
    assert trusted_events[0]["actor"] == "tester"
    assert json.loads(trusted_events[0]["cause"]) == {"from": "WARRANTED", "to": "TRUSTED"}

    # no change -> no transition, no extra event
    assert apply_fold(conn, w.id, policy, actor="tester") is None
    assert len(_events(conn, "fold.")) == 1

    # break the load-bearing claim -> REVOKED under default policy
    apply_claim_state(conn, w.id, "c-rs256", "BROKEN", actor="tester", cause=None)
    assert apply_fold(conn, w.id, policy, actor="tester") == ("TRUSTED", "REVOKED")
    row = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()
    assert row["trust_state"] == "REVOKED"
    revoked_events = _events(conn, "fold.revoked")
    assert len(revoked_events) == 1
    assert json.loads(revoked_events[0]["cause"]) == {"from": "TRUSTED", "to": "REVOKED"}
    assert len(_events(conn, "fold.")) == 2  # exactly one fold event per transition


# --- atomicity: state change + audit event commit in ONE transaction (or neither) -------


def _claim_state(conn, w, cid: str) -> str:
    return conn.execute(
        "SELECT state FROM claim WHERE warrant_id = ? AND id = ?", (w.id, cid)
    ).fetchone()["state"]


def _trust_state(conn, w) -> str:
    return conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()[
        "trust_state"
    ]


def test_apply_claim_state_commits_state_and_event_together(stored):
    conn, w = stored
    assert apply_claim_state(conn, w.id, "c-rs256", "BROKEN", actor="t", cause=None) is True
    assert _claim_state(conn, w, "c-rs256") == "BROKEN"
    assert len(_events(conn, "claim.")) == 1  # both persisted


def test_apply_claim_state_rolls_back_when_audit_write_fails(stored, monkeypatch):
    """Crash injected AFTER the state UPDATE, BEFORE the audit event: the pair rolls
    back, so NO partial state change is committed and NO event is written."""
    conn, w = stored

    def boom(*a, **k):
        raise RuntimeError("simulated crash before audit-event write")

    monkeypatch.setattr(store, "_append_event_sql", boom)
    with pytest.raises(RuntimeError):
        apply_claim_state(conn, w.id, "c-rs256", "BROKEN", actor="t", cause=None)
    # rolled back: state unchanged, no claim event persisted
    assert _claim_state(conn, w, "c-rs256") == "VERIFIED"
    assert _events(conn, "claim.") == []


def test_apply_fold_commits_trust_and_event_together(stored):
    conn, w = stored
    apply_claim_state(conn, w.id, "c-rs256", "BROKEN", actor="t", cause=None)  # load-bearing
    assert apply_fold(conn, w.id, FoldPolicy(), actor="t") == ("WARRANTED", "REVOKED")
    assert _trust_state(conn, w) == "REVOKED"
    assert len(_events(conn, "fold.")) == 1  # both persisted


def test_apply_fold_rolls_back_when_audit_write_fails(stored, monkeypatch):
    conn, w = stored
    apply_claim_state(conn, w.id, "c-rs256", "BROKEN", actor="t", cause=None)  # real commit

    def boom(*a, **k):
        raise RuntimeError("simulated crash before fold-event write")

    monkeypatch.setattr(store, "_append_event_sql", boom)
    with pytest.raises(RuntimeError):
        apply_fold(conn, w.id, FoldPolicy(), actor="t")
    # rolled back: trust state stays WARRANTED, no fold event
    assert _trust_state(conn, w) == "WARRANTED"
    assert _events(conn, "fold.") == []
