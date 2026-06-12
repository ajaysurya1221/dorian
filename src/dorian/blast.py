"""Blast radius: downstream warrants reachable from a path or warrant.

Walks the store's `derives` table, whose rows are (from_warrant, to_warrant) =
(downstream child, upstream parent) — `store.upsert_warrant` inserts one row per
`Warrant.derives_from` parent. "Who depends on the seed" therefore selects
from_warrant where to_warrant is in the frontier. The table is rebuilt from
sidecars by `dorian sync`, so blast output is a pure index query: deterministic
and reconstructible (no local-history rows involved).

Supersede lineage: a re-seal with --supersede replaces the upstream sidecar, so
a downstream `derives_from` keeps the now-dead predecessor id. Each frontier
warrant is therefore expanded with the predecessor ids reachable through the
stored `supersedes` edges (current warrants only — replaced sidecars are gone,
so the chain is as deep as the surviving rows record), and downstream hits are
reported `via` the live successor. Without this, one routine doc re-seal would
permanently blind blast/recall for the whole downstream graph.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dorian import store


def blast(repo: Path, target: str, max_depth: int = 8) -> list[dict]:
    """Downstream warrants of `target` (a repo-relative path or a warrant id),
    as dicts of {warrant_id, artifact_uri, via, depth, trust_state}; seeds
    themselves are not listed. Reads the existing index (no sync)."""
    conn = store.connect(Path(repo).resolve())
    try:
        return blast_conn(conn, target, max_depth)
    finally:
        conn.close()


def _predecessors(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Reverse supersedes edges from CURRENT warrant rows: successor id ->
    superseded ids. Replaced sidecars no longer exist, so the map holds exactly
    the lineage the surviving sidecars record (rebuildable by `dorian sync`)."""
    preds: dict[str, list[str]] = {}
    for r in conn.execute("SELECT id, supersedes FROM warrant WHERE supersedes IS NOT NULL"):
        preds.setdefault(r["id"], []).append(r["supersedes"])
    return preds


def _lineage(warrant_id: str, predecessors: dict[str, list[str]]) -> list[str]:
    """The warrant id plus every id it transitively supersedes, sorted for a
    deterministic edge scan; cycle-safe via the seen set."""
    seen = {warrant_id}
    queue = [warrant_id]
    while queue:
        for pred in predecessors.get(queue.pop(), ()):
            if pred not in seen:
                seen.add(pred)
                queue.append(pred)
    return sorted(seen)


def blast_conn(conn: sqlite3.Connection, target: str, max_depth: int = 8) -> list[dict]:
    """`blast` over an already-open store connection.

    Seeds: a `sha256:` target is a warrant id; anything else is matched against
    read-set resource uris (every warrant that read the path). The walk is
    breadth-first, cycle-safe via a seen set, bounded by `max_depth`, and
    deterministic: each frontier is sorted, and a warrant linked in by several
    upstreams at the same depth gets the lexicographically first `via`. Each
    frontier warrant also matches derives edges pointing at any id it
    supersedes (transitively), so downstream warrants sealed against a
    predecessor stay reachable after a --supersede re-seal.
    """
    if target.startswith("sha256:"):
        seeds = [target]
    else:
        seeds = sorted(
            {
                r["warrant_id"]
                for r in conn.execute(
                    "SELECT DISTINCT warrant_id FROM resource WHERE uri = ?", (target,)
                )
            }
        )
    predecessors = _predecessors(conn)
    seen = set(seeds)
    hits: list[dict] = []
    frontier = seeds
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        edges: list[tuple[str, str]] = []  # (downstream, live upstream that linked it)
        for upstream in frontier:
            for alias in _lineage(upstream, predecessors):
                edges.extend(
                    (r["from_warrant"], upstream)
                    for r in conn.execute(
                        "SELECT from_warrant FROM derives WHERE to_warrant = ?",
                        (alias,),
                    )
                )
        frontier = []
        for wid, via in sorted(edges):
            if wid in seen:
                continue
            seen.add(wid)
            w = conn.execute(
                "SELECT artifact_uri, trust_state FROM warrant WHERE id = ?", (wid,)
            ).fetchone()
            hits.append(
                {
                    "warrant_id": wid,
                    "artifact_uri": w["artifact_uri"] if w else None,
                    "via": via,
                    "depth": depth,
                    "trust_state": w["trust_state"] if w else "UNKNOWN",
                }
            )
            frontier.append(wid)
    return hits
