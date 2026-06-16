"""Trust fold: derive a warrant's trust state from its claim states.

`fold` is a pure function over (claim_state, load_bearing) pairs; the apply_*
helpers persist claim/trust transitions through the store and append one audit
event per actual change (no-ops emit nothing).

Atomicity: a state change and its audit event are committed in ONE transaction
(store.apply_claim_state_atomic / apply_trust_state_atomic), so a crash can never
leave a persisted state change without its audit event — either both land or
neither does.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from dorian import store
from dorian.model import FoldPolicy


def fold(states: list[tuple[str, bool]], policy: FoldPolicy) -> str:
    """Fold claim states into a trust state. states = (claim_state, load_bearing).

    Only BROKEN and ERRORED states influence the result, so UNBACKED and
    SUPERSEDED (like VERIFIED/PROPOSED) never affect the fold.

    `policy.degrade_on` is intentionally unused in v0.0: there is no STALE
    claim state in this wave, so every non-revoking BROKEN degrades under
    either degrade_on value.
    """
    broken = [lb for s, lb in states if s == "BROKEN"]
    if broken and (policy.revoke_on == "any_broken" or any(broken)):
        return "REVOKED"
    if broken:
        return "DEGRADED"
    if any(s == "ERRORED" for s, _ in states):
        return "UNKNOWN"
    return "TRUSTED"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_claim_state(
    conn: sqlite3.Connection,
    warrant_id: str,
    claim_id: str,
    new_state: str,
    *,
    actor: str,
    cause: dict | None,
) -> bool:
    """Persist a claim state transition; no-op (False) if the state is unchanged."""
    row = conn.execute(
        "SELECT state FROM claim WHERE warrant_id = ? AND id = ?", (warrant_id, claim_id)
    ).fetchone()
    if row is None:
        raise KeyError(f"{warrant_id}:{claim_id}")
    if row["state"] == new_state:
        return False
    store.apply_claim_state_atomic(
        conn,
        warrant_id,
        claim_id,
        new_state,
        _now_iso(),
        actor=actor,
        kind="claim." + new_state.lower(),
        cause=cause,
    )
    return True


def apply_fold(
    conn: sqlite3.Connection, warrant_id: str, policy: FoldPolicy, *, actor: str
) -> tuple[str, str] | None:
    """Recompute the fold; persist + emit one fold event if trust_state changed."""
    row = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (warrant_id,)).fetchone()
    if row is None:
        raise KeyError(warrant_id)
    old = row["trust_state"]
    claim_states = store.get_claim_states(conn, warrant_id)
    new = fold([(c["state"], c["load_bearing"]) for c in claim_states], policy)
    if new == old:
        return None
    store.apply_trust_state_atomic(
        conn,
        warrant_id,
        new,
        actor=actor,
        kind="fold." + new.lower(),
        cause={"from": old, "to": new},
    )
    return (old, new)
