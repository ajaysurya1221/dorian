"""Event-log reporting: a plain-text digest of a recent window, plus the full
audit export (`report --audit`) as stable dorian-audit-v1 JSONL.

The audit export is local history, so stored event times are emitted as-is —
but the export itself adds no new timestamp (byte-identical across runs).
Checker details are normally stable codes ('span_changed_or_removed'), but C5
details can embed observed data values (shell stdout, domain samples), so an
exported cause's 'detail' string is truncated to 160 chars to bound any
source-content carryover.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dorian import store

_SPEC_RE = re.compile(r"^(\d+)([dh])$")


def _cutoff(since_spec: str) -> str:
    """Parse '7d' / '24h' into an RFC3339 UTC cutoff; ValueError on anything else."""
    m = _SPEC_RE.match(since_spec.strip())
    if not m:
        raise ValueError(f"bad since spec {since_spec!r}: use '<n>d' or '<n>h' (e.g. 7d, 24h)")
    n, unit = int(m.group(1)), m.group(2)
    try:  # n is unbounded: timedelta or the subtraction can overflow
        delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
        return (datetime.now(UTC) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OverflowError:
        raise ValueError(f"bad since spec {since_spec!r}: window too large") from None


def report_events(repo: Path, since_spec: str = "7d") -> dict:
    """The digest as a stable dict (the --json payload; report_since renders it)."""
    cutoff = _cutoff(since_spec)
    conn = store.connect(repo)
    try:
        events = store.events_since(conn, cutoff)
        warrants = {w["id"]: w for w in store.get_warrants(conn)}
    finally:
        conn.close()

    by_warrant: dict[str, list[sqlite3.Row]] = {}
    for ev in events:
        by_warrant.setdefault(ev["warrant_id"], []).append(ev)

    out = []
    for wid, evs in by_warrant.items():
        w = warrants.get(wid)
        out.append(
            {
                "warrant_id": wid,
                "artifact_uri": w["artifact_uri"] if w else None,
                "trust_state": w["trust_state"] if w else "UNKNOWN",
                "events": [
                    {
                        "kind": ev["kind"],
                        "claim_id": ev["claim_id"],
                        "cause": ev["cause"],
                        "at": ev["at"],
                    }
                    for ev in evs
                ],
            }
        )
    return {"since": since_spec, "cutoff": cutoff, "warrants": out}


_AUDIT_SCHEMA = "dorian-audit-v1"
_DETAIL_MAX = 160


def audit_lines(repo: Path, since_spec: str | None = None) -> list[str]:
    """The full event log as audit JSONL lines, seq ascending; `since_spec`
    (when given) filters to events at or after its cutoff."""
    cutoff = _cutoff(since_spec) if since_spec is not None else None
    conn = store.connect(repo)
    try:
        if cutoff is None:
            events = conn.execute("SELECT * FROM event ORDER BY seq").fetchall()
        else:
            events = store.events_since(conn, cutoff)
    finally:
        conn.close()
    lines = []
    for ev in events:
        cause = json.loads(ev["cause"]) if ev["cause"] is not None else None
        if isinstance(cause, dict) and isinstance(cause.get("detail"), str):
            cause["detail"] = cause["detail"][:_DETAIL_MAX]
        lines.append(
            json.dumps(
                {
                    "schema": _AUDIT_SCHEMA,
                    "seq": ev["seq"],
                    "at": ev["at"],
                    "actor": ev["actor"],
                    "kind": ev["kind"],
                    "warrant_id": ev["warrant_id"],
                    "claim_id": ev["claim_id"],
                    "cause": cause,
                },
                sort_keys=True,
            )
        )
    return lines


def report_since(repo: Path, since_spec: str = "7d") -> str:
    data = report_events(repo, since_spec)
    lines = [f"events since {data['cutoff']} ({data['since']})"]
    if not data["warrants"]:
        lines.append("  (none)")
    for w in data["warrants"]:
        uri = w["artifact_uri"] or "(unindexed)"
        lines.append(f"{uri} [{w['trust_state']}] {w['warrant_id'][:23]}")
        for ev in w["events"]:
            claim = ev["claim_id"] or "-"
            cause = ev["cause"] or ""
            lines.append(f"  {ev['kind']:14} {claim:6} {cause} @ {ev['at']}".rstrip())
    return "\n".join(lines) + "\n"
