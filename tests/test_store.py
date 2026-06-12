"""Store acceptance tests: sync rebuild, bindings, claim states, events.

Matrix:
(a) sync indexes 2 hand-built sidecars; double-sync yields identical row sets
(b) events survive sync
(c) deleting a sidecar then sync removes its rows
(d) tampered sidecar raises IntegrityError
(e) claims_for_paths returns exactly the claims watching/supported-by a path
(f) new-warrant claim states init VERIFIED/UNBACKED; existing states preserved
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from dorian import store
from dorian.model import (
    CheckerSpec,
    Claim,
    FoldPolicy,
    IntegrityError,
    ProducedBy,
    ReadSetEntry,
    Warrant,
)

SEALED_AT = "2026-06-11T00:00:00Z"


def _produced_by() -> ProducedBy:
    return ProducedBy(runner="manual", captured_at=SEALED_AT)


def warrant_one() -> Warrant:
    """docs/design.md: one backed claim, one unbacked claim, one unsupported entry."""
    return Warrant.create(
        artifact_uri="docs/design.md",
        artifact_hash="sha256:d1",
        git_ref="ref1",
        produced_by=_produced_by(),
        read_set=(
            ReadSetEntry(
                id="rs-0", uri="src/config.py", selector="L1-1", hash="sha256:a", version="ref1"
            ),
            ReadSetEntry(
                id="rs-1", uri="src/routes.py", selector=None, hash="sha256:b", version="ref1"
            ),
            # read but supported by no claim: must never surface in claims_for_paths
            ReadSetEntry(
                id="rs-2", uri="src/auth.py", selector=None, hash="sha256:c", version="ref1"
            ),
        ),
        claims=(
            Claim(
                id="c-timeout",
                text="The default request timeout is 30 seconds.",
                kind="quantity",
                load_bearing=True,
                supports=("rs-0",),
                checkers=(CheckerSpec(type="C1", program="rs-0", watch=("src/config.py",)),),
            ),
            Claim(
                id="c-login",
                text="Login is served at /v1/login.",
                kind="reference",
                load_bearing=False,
                supports=("rs-1",),
            ),
        ),
        fold_policy=FoldPolicy(),
        sealed_at=SEALED_AT,
        derives_from=("sha256:parent",),
    )


def warrant_two() -> Warrant:
    """docs/other.md: a single backed claim over data/lots.csv."""
    return Warrant.create(
        artifact_uri="docs/other.md",
        artifact_hash="sha256:d2",
        git_ref="ref1",
        produced_by=_produced_by(),
        read_set=(
            ReadSetEntry(
                id="rs-0", uri="data/lots.csv", selector=None, hash="sha256:e", version="ref1"
            ),
        ),
        claims=(
            Claim(
                id="c-rows",
                text="The lots dataset has 4 rows.",
                kind="quantity",
                load_bearing=True,
                supports=("rs-0",),
                checkers=(CheckerSpec(type="C5", program="rowcount==4", watch=("data/lots.csv",)),),
            ),
        ),
        fold_policy=FoldPolicy(),
        sealed_at=SEALED_AT,
    )


TABLE_QUERIES = {
    "warrant": "SELECT * FROM warrant ORDER BY id",
    "resource": "SELECT * FROM resource ORDER BY id",
    "claim": "SELECT * FROM claim ORDER BY warrant_id, id",
    "binding": (
        "SELECT * FROM binding ORDER BY warrant_id, claim_id, "
        "COALESCE(resource_entry_id, ''), COALESCE(checker, ''), COALESCE(watch_path, '')"
    ),
    "derives": "SELECT * FROM derives ORDER BY from_warrant, to_warrant",
    "event": "SELECT * FROM event ORDER BY seq",
}


def snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {t: [tuple(r) for r in conn.execute(q)] for t, q in TABLE_QUERIES.items()}


@pytest.fixture
def synced(fixture_repo: Path) -> tuple[Path, sqlite3.Connection, Warrant, Warrant]:
    w1, w2 = warrant_one(), warrant_two()
    w1.dump(w1.sidecar_path(fixture_repo))
    w2.dump(w2.sidecar_path(fixture_repo))
    conn = store.connect(fixture_repo)
    assert store.sync(fixture_repo, conn) == 2
    return fixture_repo, conn, w1, w2


# --- (a) sync + idempotency ----------------------------------------------------


def test_sync_indexes_both_warrants(synced):
    _, conn, w1, w2 = synced
    ids = {r["id"] for r in store.get_warrants(conn)}
    assert ids == {w1.id, w2.id}
    resource_ids = {r["id"] for r in conn.execute("SELECT id FROM resource")}
    assert resource_ids == {
        f"{w1.id}:rs-0",
        f"{w1.id}:rs-1",
        f"{w1.id}:rs-2",
        f"{w2.id}:rs-0",
    }
    # bindings: w1 c-timeout = supports + checker-watch; c-login = supports;
    # w2 c-rows = supports + checker-watch
    n = conn.execute("SELECT COUNT(*) AS n FROM binding").fetchone()["n"]
    assert n == 5
    derives = [tuple(r) for r in conn.execute("SELECT from_warrant, to_warrant FROM derives")]
    assert derives == [(w1.id, "sha256:parent")]


def test_double_sync_is_idempotent(synced):
    repo, conn, _, _ = synced
    before = snapshot(conn)
    assert store.sync(repo, conn) == 2
    assert snapshot(conn) == before


def test_duplicate_sidecar_indexes_once(synced):
    repo, conn, w1, w2 = synced
    # byte-identical copy at a second location loads to the same content-addressed id
    dup = repo / "docs" / "copy.md.warrant"
    dup.write_bytes(w2.sidecar_path(repo).read_bytes())
    assert store.sync(repo, conn) == 2
    assert {r["id"] for r in store.get_warrants(conn)} == {w1.id, w2.id}
    # deterministic winner: first sidecar in sorted scan order
    row = conn.execute("SELECT sidecar_path FROM warrant WHERE id = ?", (w2.id,)).fetchone()
    assert row["sidecar_path"] == "docs/copy.md.warrant"


def test_sync_skips_excluded_dirs(synced):
    repo, conn, _, _ = synced
    # garbage sidecars in skip dirs would crash sync if scanned
    for d in (".warrant", ".venv", ".git"):
        p = repo / d / "junk.md.warrant"
        p.parent.mkdir(exist_ok=True)
        p.write_text("not json at all")
    assert store.sync(repo, conn) == 2


# --- (b) events survive sync ---------------------------------------------------


def test_events_survive_sync(synced):
    repo, conn, w1, _ = synced
    seq = store.append_event(
        conn,
        warrant_id=w1.id,
        claim_id="c-timeout",
        actor="tester",
        kind="rechecked",
        cause={"path": "src/config.py"},
    )
    assert isinstance(seq, int)
    store.sync(repo, conn)
    rows = store.events_since(conn, "2000-01-01")
    assert [r["seq"] for r in rows] == [seq]
    assert rows[0]["warrant_id"] == w1.id
    assert rows[0]["claim_id"] == "c-timeout"
    assert rows[0]["actor"] == "tester"
    assert rows[0]["kind"] == "rechecked"
    assert json.loads(rows[0]["cause"]) == {"path": "src/config.py"}


def test_event_at_is_rfc3339_and_seen_from_same_day_since(synced):
    """events stored today must be returned for a since_iso of today's midnight.

    The DDL default datetime('now') writes 'YYYY-MM-DD HH:MM:SS'; because
    ' ' < 'T', a lexicographic compare against an RFC3339 since_iso would
    silently drop every same-day event. append_event must store RFC3339.
    """
    _, conn, w1, _ = synced
    seq = store.append_event(conn, warrant_id=w1.id, kind="rechecked")
    at = conn.execute("SELECT at FROM event WHERE seq = ?", (seq,)).fetchone()["at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", at)
    day_start = at[:10] + "T00:00:00Z"
    assert seq in [r["seq"] for r in store.events_since(conn, day_start)]


# --- (c) sidecar removal -------------------------------------------------------


def test_removed_sidecar_rows_are_deleted(synced):
    repo, conn, w1, w2 = synced
    w2.sidecar_path(repo).unlink()
    assert store.sync(repo, conn) == 1
    assert {r["id"] for r in store.get_warrants(conn)} == {w1.id}
    for table, col in [
        ("resource", "warrant_id"),
        ("claim", "warrant_id"),
        ("binding", "warrant_id"),
        ("derives", "from_warrant"),
    ]:
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} = ?", (w2.id,)).fetchone()[
            "n"
        ]
        assert n == 0, f"stale {table} rows for removed warrant"
    # w1 rows untouched
    assert store.get_claim_states(conn, w1.id) != []


# --- (d) tampered sidecar ------------------------------------------------------


def test_tampered_sidecar_raises_integrity_error(synced):
    repo, conn, _, w2 = synced
    before = snapshot(conn)
    p = w2.sidecar_path(repo)
    d = json.loads(p.read_text())
    d["warrant"]["claims"][0]["text"] = "tampered"
    p.write_text(json.dumps(d))
    with pytest.raises(IntegrityError):
        store.sync(repo, conn)
    # docstring contract: raised "before any rows are touched"
    assert snapshot(conn) == before


# --- (e) claims_for_paths ------------------------------------------------------


def test_claims_for_paths_exact_matches(synced):
    _, conn, w1, w2 = synced
    # watched + supported by the same claim: one DISTINCT row
    assert store.claims_for_paths(conn, ["src/config.py"]) == [
        {"warrant_id": w1.id, "claim_id": "c-timeout"}
    ]
    # supports-only edge (claim has no checkers)
    assert store.claims_for_paths(conn, ["src/routes.py"]) == [
        {"warrant_id": w1.id, "claim_id": "c-login"}
    ]
    assert store.claims_for_paths(conn, ["data/lots.csv"]) == [
        {"warrant_id": w2.id, "claim_id": "c-rows"}
    ]


def test_claims_for_paths_negative_and_multi(synced):
    _, conn, w1, w2 = synced
    # read-set entry supported by no claim must not surface
    assert store.claims_for_paths(conn, ["src/auth.py"]) == []
    assert store.claims_for_paths(conn, ["src/unrelated.py"]) == []
    assert store.claims_for_paths(conn, []) == []
    got = store.claims_for_paths(conn, ["src/config.py", "data/lots.csv"])
    assert sorted(got, key=lambda d: d["claim_id"]) == sorted(
        [
            {"warrant_id": w1.id, "claim_id": "c-timeout"},
            {"warrant_id": w2.id, "claim_id": "c-rows"},
        ],
        key=lambda d: d["claim_id"],
    )


def test_claims_for_paths_handles_large_path_lists(synced):
    """Path lists past SQLITE_MAX_VARIABLE_NUMBER (32766) must not blow up:
    2 bound params per path means ~16k paths overflow without chunking."""
    _, conn, w1, w2 = synced
    paths = [f"src/nothing_{i}.py" for i in range(20_000)]
    paths += ["src/config.py", "data/lots.csv"]
    got = store.claims_for_paths(conn, paths)
    assert got == [
        {"warrant_id": wid, "claim_id": cid}
        for wid, cid in sorted([(w1.id, "c-timeout"), (w2.id, "c-rows")])
    ]


def test_claims_for_paths_glob_watch(synced):
    """A glob watch path ('src/*.py') must trigger on any matching changed path;
    non-matching paths must not trigger it."""
    repo, conn, w1, w2 = synced
    w3 = Warrant.create(
        artifact_uri="docs/glob.md",
        artifact_hash="sha256:d3",
        git_ref="ref1",
        produced_by=_produced_by(),
        read_set=(
            ReadSetEntry(
                id="rs-0", uri="src/config.py", selector=None, hash="sha256:f", version="ref1"
            ),
        ),
        claims=(
            Claim(
                id="c-src",
                text="All source modules follow the layout convention.",
                kind="fact",
                load_bearing=False,
                checkers=(CheckerSpec(type="C5", program="shell:true", watch=("src/*.py",)),),
            ),
        ),
        fold_policy=FoldPolicy(),
        sealed_at=SEALED_AT,
    )
    w3.dump(w3.sidecar_path(repo))
    assert store.sync(repo, conn) == 3

    # src/config.py matches both the literal watch (w1) and the glob (w3)
    assert store.claims_for_paths(conn, ["src/config.py"]) == sorted(
        [
            {"warrant_id": w1.id, "claim_id": "c-timeout"},
            {"warrant_id": w3.id, "claim_id": "c-src"},
        ],
        key=lambda d: (d["warrant_id"], d["claim_id"]),
    )
    # a fresh file nobody watches literally still matches the glob
    assert store.claims_for_paths(conn, ["src/new_module.py"]) == [
        {"warrant_id": w3.id, "claim_id": "c-src"}
    ]
    # non-matching changed paths must not trigger the glob
    assert store.claims_for_paths(conn, ["docs/notes.md", "data/lots.csv"]) == [
        {"warrant_id": w2.id, "claim_id": "c-rows"}
    ]


# --- rename log ------------------------------------------------------------------


def test_rename_log_survives_sync_and_resolves_chains(synced):
    repo, conn, _, _ = synced
    store.record_renames(conn, {"src/auth.py": "src/tokens.py"}, "2026-06-11T00:00:00Z")
    store.record_renames(conn, {"src/tokens.py": "src/jwt.py"}, "2026-06-12T00:00:00Z")
    assert store.sync(repo, conn) == 2  # sync must preserve rename_log like events
    assert store.persisted_renames(conn) == {
        "src/auth.py": "src/jwt.py",  # chain a -> b -> c resolves to the latest
        "src/tokens.py": "src/jwt.py",
    }
    # idempotent re-record of an already-known rename
    store.record_renames(conn, {"src/auth.py": "src/tokens.py"}, "2026-06-13T00:00:00Z")
    n = conn.execute("SELECT COUNT(*) AS n FROM rename_log").fetchone()["n"]
    assert n == 2


def test_persisted_renames_is_cycle_safe(synced):
    _, conn, _, _ = synced
    store.record_renames(conn, {"a.py": "b.py"}, "2026-06-11T00:00:00Z")
    store.record_renames(conn, {"b.py": "a.py"}, "2026-06-11T00:00:00Z")
    resolved = store.persisted_renames(conn)  # must terminate
    assert set(resolved) == {"a.py", "b.py"}


# --- (f) claim state init + preservation ---------------------------------------


def test_new_warrant_claim_states_initialized_per_checkers(synced):
    _, conn, w1, w2 = synced
    states = {d["claim_id"]: d for d in store.get_claim_states(conn, w1.id)}
    assert states["c-timeout"]["state"] == "VERIFIED"
    assert states["c-timeout"]["load_bearing"] is True
    assert states["c-login"]["state"] == "UNBACKED"
    assert states["c-login"]["load_bearing"] is False
    assert store.get_claim_states(conn, w2.id) == [
        {"claim_id": "c-rows", "state": "VERIFIED", "load_bearing": True}
    ]


def test_existing_states_preserved_across_resync(synced):
    repo, conn, w1, _ = synced
    store.set_claim_state(conn, w1.id, "c-timeout", "BROKEN", "2026-06-12T00:00:00Z")
    store.set_trust_state(conn, w1.id, "DEGRADED")
    assert store.sync(repo, conn) == 2
    states = {d["claim_id"]: d["state"] for d in store.get_claim_states(conn, w1.id)}
    assert states == {"c-timeout": "BROKEN", "c-login": "UNBACKED"}
    row = conn.execute(
        "SELECT trust_state, state_changed_at FROM warrant "
        "JOIN claim ON claim.warrant_id = warrant.id WHERE warrant.id = ? AND claim.id = ?",
        (w1.id, "c-timeout"),
    ).fetchone()
    assert row["trust_state"] == "DEGRADED"
    assert row["state_changed_at"] == "2026-06-12T00:00:00Z"
