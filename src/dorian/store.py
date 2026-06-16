"""SQLite store: a derived index over `.warrant` sidecars.

Sidecars are the source of truth. The DB is rebuildable at any time via `sync()`;
the only rows that are not reconstructible are events and the rename log
(both local history).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DORIAN_DIR = ".warrant"
DB_NAME = "index.sqlite"

DDL = """
CREATE TABLE IF NOT EXISTS warrant (
  id TEXT PRIMARY KEY,
  artifact_uri TEXT NOT NULL,
  artifact_hash TEXT NOT NULL,
  sidecar_path TEXT NOT NULL,
  produced_by TEXT NOT NULL,          -- JSON
  fold_policy TEXT NOT NULL,          -- JSON
  trust_state TEXT NOT NULL DEFAULT 'WARRANTED',
  supersedes TEXT,
  sealed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warrant_artifact ON warrant(artifact_uri);
CREATE INDEX IF NOT EXISTS idx_warrant_state ON warrant(trust_state);

CREATE TABLE IF NOT EXISTS resource (
  id TEXT PRIMARY KEY,                -- f"{warrant_id}:{entry_id}"
  warrant_id TEXT NOT NULL REFERENCES warrant(id) ON DELETE CASCADE,
  entry_id TEXT NOT NULL,
  uri TEXT NOT NULL,
  selector TEXT,
  hash TEXT NOT NULL,
  version TEXT,
  scope TEXT NOT NULL DEFAULT 'project'
);
CREATE INDEX IF NOT EXISTS idx_resource_uri ON resource(uri);
CREATE INDEX IF NOT EXISTS idx_resource_warrant ON resource(warrant_id);

CREATE TABLE IF NOT EXISTS claim (
  warrant_id TEXT NOT NULL REFERENCES warrant(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  text TEXT NOT NULL,
  kind TEXT NOT NULL,
  anchor TEXT,                        -- JSON
  load_bearing INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'PROPOSED',
  state_changed_at TEXT,
  PRIMARY KEY (warrant_id, id)
);
CREATE INDEX IF NOT EXISTS idx_claim_state ON claim(state);

CREATE TABLE IF NOT EXISTS binding (
  warrant_id TEXT NOT NULL,
  claim_id TEXT NOT NULL,
  resource_entry_id TEXT,             -- supports edge (ReadSetEntry id) or NULL
  checker TEXT,                       -- JSON CheckerSpec or NULL
  watch_path TEXT                     -- denormalized: one row per watch path/glob
);
CREATE INDEX IF NOT EXISTS idx_binding_watch ON binding(watch_path);
CREATE INDEX IF NOT EXISTS idx_binding_claim ON binding(warrant_id, claim_id);

CREATE TABLE IF NOT EXISTS derives (
  from_warrant TEXT NOT NULL,
  to_warrant TEXT NOT NULL,
  via TEXT,
  PRIMARY KEY (from_warrant, to_warrant)
);

CREATE TABLE IF NOT EXISTS event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  warrant_id TEXT NOT NULL,
  claim_id TEXT,
  actor TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  cause TEXT,                         -- JSON
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_event_warrant ON event(warrant_id, seq);
CREATE INDEX IF NOT EXISTS idx_event_at ON event(at);

CREATE TABLE IF NOT EXISTS rename_log (
  old_path TEXT NOT NULL,
  new_path TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (old_path, new_path)
);
"""


def db_path(repo: Path) -> Path:
    return repo / DORIAN_DIR / DB_NAME


def connect(repo: Path) -> sqlite3.Connection:
    """Open (creating if needed) the repo's index DB with WAL + FK enforcement."""
    d = repo / DORIAN_DIR
    d.mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("index.sqlite\nindex.sqlite-*\n")
    conn = sqlite3.connect(db_path(repo))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    return conn


# --- implemented by store task (wave 1) ---------------------------------------

import fnmatch  # noqa: E402  (extensions live below the frozen scaffold above)
import json  # noqa: E402

from dorian.model import Warrant  # noqa: E402

_SKIP_DIRS = frozenset({".git", ".venv", DORIAN_DIR})


def sync(repo: Path, conn: sqlite3.Connection) -> int:
    """Rebuild the index from `**/*.warrant` sidecars; return warrants indexed.

    Sidecars under `.git`, `.venv`, and `.warrant` are skipped. Each sidecar is
    loaded via `Warrant.load`, whose integrity check raises `IntegrityError` on
    tamper (propagated, before any rows are touched). Rows for warrant ids whose
    sidecars no longer exist are removed; events and rename_log are never
    touched (both are local history, not derivable from sidecars).

    Claim states for already-indexed warrant ids are preserved. Claims of NEW
    warrant ids initialize to 'UNBACKED' when they carry no checkers, else
    'VERIFIED': seal refuses to write a sidecar whose checkers fail, so a
    committed sidecar implies its checkers were green at seal time. Idempotent:
    two syncs in a row produce identical row sets.

    Byte-identical sidecars at several locations share one content-addressed id
    and index once (first sidecar in sorted scan order wins sidecar_path). The
    rebuild is a single transaction: committed at the end, rolled back on error.
    """
    warrants: dict[str, tuple[Warrant, str]] = {}
    for p in sorted(repo.rglob("*.warrant")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        w = Warrant.load(p)
        warrants.setdefault(w.id, (w, rel.as_posix()))

    try:
        indexed = [r["id"] for r in conn.execute("SELECT id FROM warrant").fetchall()]
        for wid in (wid for wid in indexed if wid not in warrants):
            conn.execute("DELETE FROM binding WHERE warrant_id = ?", (wid,))
            conn.execute("DELETE FROM derives WHERE from_warrant = ?", (wid,))
            conn.execute("DELETE FROM warrant WHERE id = ?", (wid,))  # cascades resource/claim
        for w, sidecar in warrants.values():
            upsert_warrant(conn, w, sidecar)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(warrants)


def upsert_warrant(conn: sqlite3.Connection, w: Warrant, sidecar_path: str) -> None:
    """Insert or rebuild all index rows (warrant/resource/claim/binding/derives)
    for one warrant. Warrant ids are content-addressed, so an existing id means
    identical content: its trust_state and claim states are preserved.

    Does NOT commit — `sync` commits once for the whole rebuild so it stays
    atomic; direct callers must commit themselves."""
    row = conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (w.id,)).fetchone()
    trust_state = row["trust_state"] if row else "WARRANTED"
    prior = {
        r["id"]: (r["state"], r["state_changed_at"])
        for r in conn.execute(
            "SELECT id, state, state_changed_at FROM claim WHERE warrant_id = ?", (w.id,)
        )
    }
    conn.execute("DELETE FROM resource WHERE warrant_id = ?", (w.id,))
    conn.execute("DELETE FROM claim WHERE warrant_id = ?", (w.id,))
    conn.execute("DELETE FROM binding WHERE warrant_id = ?", (w.id,))
    conn.execute("DELETE FROM derives WHERE from_warrant = ?", (w.id,))
    conn.execute(
        """INSERT INTO warrant
             (id, artifact_uri, artifact_hash, sidecar_path, produced_by,
              fold_policy, trust_state, supersedes, sealed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             artifact_uri = excluded.artifact_uri,
             artifact_hash = excluded.artifact_hash,
             sidecar_path = excluded.sidecar_path,
             produced_by = excluded.produced_by,
             fold_policy = excluded.fold_policy,
             supersedes = excluded.supersedes,
             sealed_at = excluded.sealed_at""",
        (
            w.id,
            w.artifact_uri,
            w.artifact_hash,
            sidecar_path,
            json.dumps(w.produced_by.to_dict(), sort_keys=True),
            json.dumps(w.fold_policy.to_dict(), sort_keys=True),
            trust_state,
            w.supersedes,
            w.sealed_at,
        ),
    )
    for e in w.read_set:
        conn.execute(
            "INSERT INTO resource (id, warrant_id, entry_id, uri, selector, hash, version, scope)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{w.id}:{e.id}", w.id, e.id, e.uri, e.selector, e.hash, e.version, e.scope),
        )
    for c in w.claims:
        state, changed_at = prior.get(c.id, ("VERIFIED" if c.checkers else "UNBACKED", None))
        conn.execute(
            "INSERT INTO claim (warrant_id, id, text, kind, anchor, load_bearing, state,"
            " state_changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                w.id,
                c.id,
                c.text,
                c.kind,
                json.dumps(c.anchor.to_dict(), sort_keys=True) if c.anchor else None,
                int(c.load_bearing),
                state,
                changed_at,
            ),
        )
        for entry_id in c.supports:
            conn.execute(
                "INSERT INTO binding (warrant_id, claim_id, resource_entry_id, checker,"
                " watch_path) VALUES (?, ?, ?, NULL, NULL)",
                (w.id, c.id, entry_id),
            )
        for spec in c.checkers:
            checker_json = json.dumps(spec.to_dict(), sort_keys=True)
            for watch_path in spec.watch:
                conn.execute(
                    "INSERT INTO binding (warrant_id, claim_id, resource_entry_id, checker,"
                    " watch_path) VALUES (?, ?, NULL, ?, ?)",
                    (w.id, c.id, checker_json, watch_path),
                )
    for parent in w.derives_from:
        conn.execute(
            "INSERT INTO derives (from_warrant, to_warrant, via) VALUES (?, ?, NULL)",
            (w.id, parent),
        )


_GLOB_CHARS = ("*", "?", "[")


def claims_for_paths(conn: sqlite3.Connection, paths: list[str]) -> list[dict]:
    """DISTINCT (warrant_id, claim_id) candidates for a set of changed paths.

    A claim is a candidate when any changed path equals one of its checker
    watch paths, fnmatch-matches it as a glob ('src/*.py' triggers on
    src/config.py), or equals the uri of a resource it supports-binds to.
    Watch rows and supports rows are fetched whole and matched in Python:
    SQL IN cannot express globs, and no bound-parameter list means no
    SQLITE_MAX_VARIABLE_NUMBER ceiling on whole-tree path lists. Signature
    is unchanged for callers."""
    if not paths:
        return []
    path_set = set(paths)
    found: set[tuple[str, str]] = set()
    for r in conn.execute(
        "SELECT DISTINCT warrant_id, claim_id, watch_path FROM binding WHERE watch_path IS NOT NULL"
    ):
        wp = r["watch_path"]
        if wp in path_set or (
            any(ch in wp for ch in _GLOB_CHARS) and any(fnmatch.fnmatch(p, wp) for p in path_set)
        ):
            found.add((r["warrant_id"], r["claim_id"]))
    for r in conn.execute(
        "SELECT DISTINCT b.warrant_id AS warrant_id, b.claim_id AS claim_id, r.uri AS uri"
        "  FROM binding b JOIN resource r"
        "    ON r.warrant_id = b.warrant_id AND r.entry_id = b.resource_entry_id"
    ):
        if r["uri"] in path_set:
            found.add((r["warrant_id"], r["claim_id"]))
    return [{"warrant_id": wid, "claim_id": cid} for wid, cid in sorted(found)]


def record_renames(conn: sqlite3.Connection, renames: dict[str, str], at_iso: str) -> None:
    """Persist observed renames (old -> new). Idempotent: a rename that is
    already logged keeps its first observed_at."""
    if not renames:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO rename_log (old_path, new_path, observed_at) VALUES (?, ?, ?)",
        [(old, new, at_iso) for old, new in renames.items()],
    )
    conn.commit()


def persisted_renames(conn: sqlite3.Connection) -> dict[str, str]:
    """Rename map resolving chains to the latest known name (a->b plus b->c
    yields {a: c, b: c}). The walk is bounded by the table size and cycle-safe:
    resolution stops as soon as a path repeats."""
    step = {
        r["old_path"]: r["new_path"]
        for r in conn.execute("SELECT old_path, new_path FROM rename_log")
    }
    resolved: dict[str, str] = {}
    for old in step:
        seen = {old}
        cur = step[old]
        while cur in step and cur not in seen:
            seen.add(cur)
            cur = step[cur]
        resolved[old] = cur
    return resolved


# --- non-committing SQL primitives (so a caller can batch them into one transaction) ---


def _set_claim_state_sql(
    conn: sqlite3.Connection, warrant_id: str, claim_id: str, state: str, at_iso: str
) -> None:
    conn.execute(
        "UPDATE claim SET state = ?, state_changed_at = ? WHERE warrant_id = ? AND id = ?",
        (state, at_iso, warrant_id, claim_id),
    )


def _set_trust_state_sql(conn: sqlite3.Connection, warrant_id: str, state: str) -> None:
    conn.execute("UPDATE warrant SET trust_state = ? WHERE id = ?", (state, warrant_id))


def _append_event_sql(
    conn: sqlite3.Connection,
    *,
    warrant_id: str,
    claim_id: str | None = None,
    actor: str = "",
    kind: str,
    cause: dict | None = None,
) -> int:
    # Explicit RFC3339 `at` (the DDL default datetime('now') yields a space
    # separator, which sorts before 'T' and breaks events_since comparisons).
    cur = conn.execute(
        "INSERT INTO event (warrant_id, claim_id, actor, kind, cause, at)"
        " VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
        (
            warrant_id,
            claim_id,
            actor,
            kind,
            json.dumps(cause, sort_keys=True) if cause is not None else None,
        ),
    )
    return int(cur.lastrowid)


def set_claim_state(
    conn: sqlite3.Connection, warrant_id: str, claim_id: str, state: str, at_iso: str
) -> None:
    _set_claim_state_sql(conn, warrant_id, claim_id, state, at_iso)
    conn.commit()


def set_trust_state(conn: sqlite3.Connection, warrant_id: str, state: str) -> None:
    _set_trust_state_sql(conn, warrant_id, state)
    conn.commit()


def append_event(
    conn: sqlite3.Connection,
    *,
    warrant_id: str,
    claim_id: str | None = None,
    actor: str = "",
    kind: str,
    cause: dict | None = None,
) -> int:
    rid = _append_event_sql(
        conn, warrant_id=warrant_id, claim_id=claim_id, actor=actor, kind=kind, cause=cause
    )
    conn.commit()
    return rid


def apply_claim_state_atomic(
    conn: sqlite3.Connection,
    warrant_id: str,
    claim_id: str,
    state: str,
    at_iso: str,
    *,
    actor: str,
    kind: str,
    cause: dict | None,
) -> None:
    """Persist a claim-state change AND its audit event in ONE transaction: both land or
    neither does. An exception (e.g. a crash before/while writing the event) rolls back the
    state UPDATE, so the store never holds a state change without its audit event. `with
    conn` commits on success and rolls back on any exception."""
    with conn:
        _set_claim_state_sql(conn, warrant_id, claim_id, state, at_iso)
        _append_event_sql(
            conn, warrant_id=warrant_id, claim_id=claim_id, actor=actor, kind=kind, cause=cause
        )


def apply_trust_state_atomic(
    conn: sqlite3.Connection,
    warrant_id: str,
    state: str,
    *,
    actor: str,
    kind: str,
    cause: dict | None,
) -> None:
    """Persist a trust-state change AND its fold audit event in ONE transaction (both or
    neither), so a crash never leaves a trust change without its event."""
    with conn:
        _set_trust_state_sql(conn, warrant_id, state)
        _append_event_sql(conn, warrant_id=warrant_id, actor=actor, kind=kind, cause=cause)


def events_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM event WHERE at >= ? ORDER BY seq", (since_iso,)).fetchall()


def get_warrants(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM warrant ORDER BY sealed_at, id").fetchall()


def get_claim_states(conn: sqlite3.Connection, warrant_id: str) -> list[dict]:
    return [
        {"claim_id": r["id"], "state": r["state"], "load_bearing": bool(r["load_bearing"])}
        for r in conn.execute(
            "SELECT id, state, load_bearing FROM claim WHERE warrant_id = ? ORDER BY id",
            (warrant_id,),
        )
    ]
