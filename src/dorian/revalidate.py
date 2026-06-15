"""Incremental revalidation: re-check claims whose watched sources changed.

Sidecars are the source of truth: candidate warrants are re-loaded from their
`.warrant` files (integrity-checked, so tampering raises IntegrityError); the
SQLite index is only used to map changed paths to candidate claims. Verdict
discipline is preserved end to end: a checker that cannot run yields ERRORED
(exit 5), never BROKEN.

Renames observed in a window are persisted to the store's rename_log so later
windows stay bound: a claim sealed against src/auth.py keeps following the
file after it becomes src/tokens.py — an edit to the renamed file is still a
candidate, and checkers resolve the old uri to its current location.

A warrant with a newly broken claim also flags its blast radius: every
downstream warrant (via the derives index) gets a 'recalled' event. The flag is
the whole deliverable — downstream checkers are not re-run, downstream states
are untouched, and exit codes still reflect only the touched warrants.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from dorian import fold as fold_mod
from dorian import gitio, store
from dorian.blast import blast_conn
from dorian.checkers.base import CheckContext, CheckResult, Verdict, run_checker
from dorian.cli import EXIT_DEGRADED, EXIT_ERRORED, EXIT_OK, EXIT_REVOKED
from dorian.model import Claim, ReadSetEntry, Warrant
from dorian.policy import ExecutionPolicy

# (warrant_id, claim_id, detail)
_Rec = tuple[str, str, str]

# cheap-to-expensive checker order: hash/regex lookups (C1, C3), then data scans
# (C5), then subprocess pytest runs (C4); unknown types sort last.
_CHECKER_COST = {"C1": 0, "C3": 1, "C5": 2, "C4": 3}


class ChangedPathsError(ValueError):
    """The changed-paths listing could not be read: caller input, never a
    sidecar integrity failure (callers must not map it to exit 4)."""


@dataclass
class RevalResult:
    broken: list[_Rec] = field(default_factory=list)
    relocated: list[_Rec] = field(default_factory=list)  # VERIFIED via relocation
    errored: list[_Rec] = field(default_factory=list)
    passed: list[_Rec] = field(default_factory=list)  # VERIFIED in place
    folds: dict[str, tuple[str, str]] = field(default_factory=dict)  # wid -> (old, new)
    artifacts: dict[str, str] = field(default_factory=dict)  # wid -> artifact uri (labels)
    # downstream warrants flagged by 'recalled' events (events only — their own
    # claim/trust states are untouched): {warrant_id, artifact_uri, depth, via}
    # where via is the newly broken upstream warrant
    recalled: list[dict] = field(default_factory=list)
    # checker-source=base advisories: a checker spec that changed on the PR (so the
    # base-approved spec was run instead), or a claim/sidecar skipped fail-closed
    notes: list[str] = field(default_factory=list)
    candidates: int = 0
    exit_code: int = 0


def revalidate(
    repo: Path,
    *,
    since: str | None = None,
    changed_paths_file: Path | None = None,
    enable_c2lite: bool = False,
    policy: ExecutionPolicy | None = None,
    checker_source: str = "head",
) -> RevalResult:
    """Re-check claims bound to the changed paths; one of `since` (git ref to
    diff from) or `changed_paths_file` (one path per line) is required. If both
    are given, `changed_paths_file` takes precedence and `since` is ignored
    (the CLI rejects the combination).

    checker_source (head | base; default head) selects which sidecar a candidate
    claim's checker SPEC is read from — orthogonal to which SOURCES are checked
    (always the working tree / PR head). `head` is today's behavior exactly. `base`
    is the public/fork-PR hardening: each claim's checker spec is resolved from the
    `since` (base) ref's sidecar, so a PR-added or PR-modified executable checker is
    never executed — only maintainer-approved (base) checker specs run. It fails
    closed (a missing/tampered base sidecar, or a claim absent on base, ERRORs and
    runs nothing) and it is NOT a sandbox: a base-approved C4 `pytest:` checker can
    still import and execute PR-head code (see docs/TRUSTED_BASE_ACTION_DESIGN.md)."""
    if since is None and changed_paths_file is None:
        raise ValueError("provide since=<git ref> or changed_paths_file=<path>")
    if checker_source not in ("head", "base"):
        raise ValueError(f"checker_source must be 'head' or 'base', got {checker_source!r}")
    if checker_source == "base" and since is None:
        raise ValueError(
            "checker-source=base needs --since <base ref>: the trusted checker spec is"
            " resolved from the base ref, which --changed-paths does not provide"
        )
    repo = repo.resolve()
    # under deny-exec/deny-shell a blocked C4/C5-shell recheck ERRORs (exit 5),
    # never silently PASSes and never folds to BROKEN — trigger-vs-truth intact
    exec_policy = policy if policy is not None else ExecutionPolicy()
    base_cache: dict[str, Warrant | None] = {}  # checker-source=base: per-artifact base sidecar
    if changed_paths_file is not None:
        # read exactly once, before any store work: a failure here is bad caller
        # input (distinct ChangedPathsError), never a sidecar integrity error
        try:
            text = changed_paths_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ChangedPathsError(f"unreadable changed-paths listing: {exc}") from exc
        changed = [line.strip() for line in text.splitlines() if line.strip()]
    conn = store.connect(repo)
    try:
        store.sync(repo, conn)  # IntegrityError on a tampered sidecar propagates
        if changed_paths_file is None:
            changed, window_renames = gitio.changed_paths(repo, since)
            store.record_renames(
                conn, window_renames, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        # effective map = persisted history (incl. this window), chains resolved
        # old -> latest, so C1/C3/C5 resolve a sealed uri to its current file
        renames = store.persisted_renames(conn)
        # bindings stored under a file's OLD name(s) must surface when its
        # CURRENT name changes: expand each changed path with every historical
        # name that resolves to it
        old_names: dict[str, list[str]] = {}
        for old, latest in renames.items():
            old_names.setdefault(latest, []).append(old)
        candidate_paths = list(changed)
        for p in changed:
            candidate_paths.extend(old_names.get(p, ()))
        candidates = store.claims_for_paths(conn, candidate_paths)
        result = RevalResult(candidates=len(candidates))
        if not candidates:
            return result

        actor = gitio.actor(repo)
        changed_set = set(changed)
        by_warrant: dict[str, list[str]] = {}
        for c in candidates:  # already sorted by (warrant_id, claim_id)
            by_warrant.setdefault(c["warrant_id"], []).append(c["claim_id"])
        newly_broken: dict[str, list[str]] = {}  # wid -> claim ids broken THIS run

        for wid, claim_ids in by_warrant.items():
            row = conn.execute("SELECT sidecar_path FROM warrant WHERE id = ?", (wid,)).fetchone()
            warrant = Warrant.load(repo / row["sidecar_path"])  # sidecar is the spec of record
            result.artifacts[wid] = warrant.artifact_uri
            entries = {e.id: e for e in warrant.read_set}
            claims = {c.id: c for c in warrant.claims}
            for cid in claim_ids:
                claim = claims[cid]
                cause = sorted(changed_set & _claim_paths(claim, entries, renames))
                store.append_event(
                    conn,
                    warrant_id=wid,
                    claim_id=cid,
                    actor=actor,
                    kind="claim.stale",
                    cause={"changed": cause},
                )
                if not claim.checkers and checker_source != "base":
                    continue  # unbacked claim: stale is recorded, nothing to re-check
                # checker-source=base: run the BASE-approved checker spec (resolved from
                # the `since` ref) against head sources, never the PR's spec. Fail closed
                # (ERRORED, never executed) when the base spec cannot be trusted.
                eff_claim = claim
                skip_reason: str | None = None
                if checker_source == "base":
                    base_w = _load_base_warrant(repo, since, warrant.artifact_uri, base_cache)
                    if base_w is None:
                        skip_reason = (
                            "checker-source=base: no readable base sidecar for this artifact"
                            " (fail-closed; not executed)"
                        )
                    else:
                        base_claim = next((c for c in base_w.claims if c.id == cid), None)
                        if base_claim is None:
                            skip_reason = (
                                "checker-source=base: claim not present on base ref"
                                " (PR-added checker; not executed)"
                            )
                        else:
                            if base_claim.checkers != claim.checkers:
                                result.notes.append(
                                    f"{warrant.artifact_uri}: {cid}: checker spec changed on PR"
                                    " — ran base-approved spec (checker-source=base)"
                                )
                            eff_claim = replace(claim, checkers=base_claim.checkers)
                if skip_reason is not None:
                    state, detail, relocated = "ERRORED", skip_reason, False
                elif not eff_claim.checkers:
                    continue  # nothing to run (head unbacked, or base claim unbacked)
                else:
                    state, detail, relocated = _check_claim(
                        repo, eff_claim, entries, renames, enable_c2lite, exec_policy
                    )
                changed_state = fold_mod.apply_claim_state(
                    conn, wid, cid, state, actor=actor, cause={"detail": detail}
                )
                rec = (wid, cid, detail)
                if state == "BROKEN":
                    result.broken.append(rec)
                    if changed_state:
                        newly_broken.setdefault(wid, []).append(cid)
                elif state == "ERRORED":
                    result.errored.append(rec)
                elif relocated:
                    result.relocated.append(rec)
                else:
                    result.passed.append(rec)
            change = fold_mod.apply_fold(conn, wid, warrant.fold_policy, actor=actor)
            if change is not None:
                result.folds[wid] = change

        # recall flags: every warrant downstream of a NEWLY broken one gets a
        # 'recalled' event (local history, like all events) — no re-check, no
        # claim/trust state change, no exit-code influence
        for wid, broken_ids in newly_broken.items():
            for hit in blast_conn(conn, wid):
                store.append_event(
                    conn,
                    warrant_id=hit["warrant_id"],
                    actor=actor,
                    kind="recalled",
                    cause={"via": wid, "claim_ids": broken_ids, "depth": hit["depth"]},
                )
                result.recalled.append(
                    {
                        "warrant_id": hit["warrant_id"],
                        "artifact_uri": hit["artifact_uri"],
                        "depth": hit["depth"],
                        "via": wid,
                    }
                )

        result.exit_code = _exit_code(conn, list(by_warrant))
        return result
    finally:
        conn.close()


def _load_base_warrant(
    repo: Path, base_ref: str, artifact_uri: str, cache: dict[str, Warrant | None]
) -> Warrant | None:
    """The artifact's sidecar AS IT EXISTS ON THE BASE REF (checker-source=base), or
    None if it is absent, unreadable, or its content-addressed id does not verify (a
    tampered base sidecar). Fail-closed by construction: None makes the caller skip,
    never execute the PR's checker. Cached per artifact for the run."""
    if artifact_uri in cache:
        return cache[artifact_uri]
    warrant: Warrant | None = None
    data = gitio.file_at_ref(repo, base_ref, artifact_uri + ".warrant")
    if data is not None:
        try:
            candidate = Warrant.from_dict(json.loads(data.decode("utf-8")))
            if Warrant.compute_id(candidate.body_dict()) == candidate.id:
                warrant = candidate  # integrity-valid base sidecar
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            warrant = None  # malformed/tampered base sidecar: fail closed
    cache[artifact_uri] = warrant
    return warrant


def _claim_paths(
    claim: Claim, entries: dict[str, ReadSetEntry], renames: dict[str, str]
) -> set[str]:
    """Paths a claim is bound to: checker watches + support uris (+ rename targets)."""
    paths: set[str] = set()
    for spec in claim.checkers:
        paths.update(spec.watch)
    for sid in claim.supports:
        entry = entries.get(sid)
        if entry is not None:
            paths.add(entry.uri)
    paths.update(renames[p] for p in list(paths) if p in renames)
    return paths


def _check_claim(
    repo: Path,
    claim: Claim,
    entries: dict[str, ReadSetEntry],
    renames: dict[str, str],
    enable_c2lite: bool,
    policy: ExecutionPolicy,
) -> tuple[str, str, bool]:
    """Run a claim's checkers cheapest-first (C1 < C3 < C5 < C4), stopping at the
    first FAIL. Returns (claim_state, detail, relocated)."""
    ctx = CheckContext(
        repo=repo,
        claim=claim,
        supports=[entries[s] for s in claim.supports if s in entries],
        rename_map=dict(renames),
        enable_c2lite=enable_c2lite,
        policy=policy,
    )
    order = sorted(
        range(len(claim.checkers)),
        key=lambda i: (
            _CHECKER_COST.get(claim.checkers[i].type, len(_CHECKER_COST)),
            claim.checkers[i].type,
        ),
    )
    results: list[CheckResult] = []
    for i in order:
        r = run_checker(ctx, i)
        results.append(r)
        if r.verdict is Verdict.FAIL:
            # self-describing break: renderers (notably md) show which checker
            # type produced the failure without widening the result records
            return "BROKEN", f"{claim.checkers[i].type}: {r.detail}", False
    error = next((r for r in results if r.verdict is Verdict.ERROR), None)
    if error is not None:
        return "ERRORED", error.detail, False
    if any(r.relocated for r in results):
        detail = next((r.detail for r in results if r.relocated and r.detail), "relocated")
        return "VERIFIED", detail, True
    return "VERIFIED", "; ".join(r.detail for r in results if r.detail), False


def _exit_code(conn: sqlite3.Connection, touched: list[str]) -> int:
    """Worst of the touched warrants' post-fold trust states. ERRORED claims
    surface as UNKNOWN here: the fold maps any ERRORED claim to UNKNOWN unless
    a coexisting BROKEN already revokes/degrades the warrant."""
    states = {
        conn.execute("SELECT trust_state FROM warrant WHERE id = ?", (wid,)).fetchone()[
            "trust_state"
        ]
        for wid in touched
    }
    if "REVOKED" in states:
        return EXIT_REVOKED
    if "DEGRADED" in states:
        return EXIT_DEGRADED
    if "UNKNOWN" in states:
        return EXIT_ERRORED
    return EXIT_OK


def render_text(result: RevalResult) -> str:
    lines = [f"checked {result.candidates} candidate claim(s)"]
    for label, rows in (
        ("BROKEN", result.broken),
        ("ERRORED", result.errored),
        ("RELOCATED", result.relocated),
        ("VERIFIED", result.passed),
    ):
        for wid, cid, detail in rows:
            lines.append(f"{label:9} {wid[:23]} {cid}  {detail}".rstrip())
    for wid, (old, new) in result.folds.items():
        lines.append(f"fold      {wid[:23]} {old} -> {new}")
    if result.recalled:
        n = len({e["warrant_id"] for e in result.recalled})
        lines.append(f"recalled: {n} downstream artifact(s)")
        for e in result.recalled:
            wid, uri = e["warrant_id"], e["artifact_uri"]
            lines.append(f"recalled  {wid[:23]} {uri}  depth={e['depth']}")
    for note in result.notes:
        lines.append(f"note      {note}")
    return "\n".join(lines) + "\n"


def render_json(result: RevalResult) -> str:
    return json.dumps(asdict(result))


MD_MARKER = "<!-- dorian -->"
MD_NOOP = "dorian: no warranted claims affected."

# md is the PR-comment body the GitHub Action posts publicly, so checker details
# get the same source-content carryover bound as `report --audit` (C5 details
# can embed observed data values; see report._DETAIL_MAX — kept equal by test).
_DETAIL_MAX = 160

_EXIT_MEANINGS = {
    EXIT_OK: "all touched warrants trusted",
    EXIT_DEGRADED: "a touched warrant is DEGRADED",
    EXIT_REVOKED: "a touched warrant is REVOKED",
    EXIT_ERRORED: "checker errors only (infra, not failures)",
}


def _md_cell(text: str) -> str:
    """One markdown detail cell: bound content carryover, escape pipes, flatten
    newlines."""
    return text[:_DETAIL_MAX].replace("|", "\\|").replace("\n", " ")


def render_md(result: RevalResult) -> str:
    """PR-comment markdown body: pure function of the result (no timestamps,
    no absolute paths). First line is always the sticky-comment marker; an
    all-quiet run renders ONLY the marker + sentinel so the GitHub Action can
    skip commenting entirely."""
    lines = [MD_MARKER]
    if result.candidates == 0 and not result.recalled:
        lines.append(MD_NOOP)
        return "\n".join(lines) + "\n"
    if result.broken:
        lines.append(
            f"### dorian: this change breaks {len(result.broken)} claim(s) in warranted artifacts"
        )
    else:
        lines.append("### dorian: warranted claims re-checked; none broken")

    rows: dict[str, list[tuple[str, str, str]]] = {}
    for verdict, recs in (
        ("BROKEN", result.broken),
        ("VERIFIED (relocated)", result.relocated),
        ("VERIFIED", result.passed),
    ):
        for wid, cid, detail in recs:
            rows.setdefault(wid, []).append((cid, verdict, detail))
    errors: dict[str, list[tuple[str, str]]] = {}
    for wid, cid, detail in result.errored:
        errors.setdefault(wid, []).append((cid, detail))

    for wid in sorted(rows.keys() | errors.keys()):
        label = result.artifacts.get(wid, wid[:23])
        lines += ["", f"#### `{label}`"]
        if wid in rows:
            lines += ["", "| claim | verdict | why |", "| --- | --- | --- |"]
            for cid, verdict, detail in rows[wid]:
                lines.append(f"| `{cid}` | {verdict} | {_md_cell(detail)} |")
        if wid in errors:  # ERROR != FAIL: listed as errors, never as breaks
            lines += ["", "Errors (checker could not run; not failures):"]
            for cid, detail in errors[wid]:
                lines.append(f"- `{cid}`: {_md_cell(detail)}")

    if result.folds:
        lines += ["", "Trust transitions:"]
        for wid, (old, new) in sorted(result.folds.items()):
            lines.append(f"- `{result.artifacts.get(wid, wid[:23])}`: {old} -> {new}")
    if result.recalled:
        lines += ["", "Recalled downstream (flagged, not re-checked):"]
        for e in result.recalled:
            lines.append(f"- `{e['artifact_uri']}` (depth {e['depth']})")
    if result.notes:  # checker-source=base advisories (PR-changed / skipped specs)
        lines += ["", "Checker-source notes (trusted-base mode):"]
        for note in result.notes:
            lines.append(f"- {_md_cell(note)}")

    checks = sum(map(len, (result.broken, result.relocated, result.errored, result.passed)))
    meaning = _EXIT_MEANINGS.get(result.exit_code, "unknown")
    lines += [
        "",
        f"{checks} checker(s) run, {len(result.broken)} broken,"
        f" {len(result.errored)} errored; exit {result.exit_code} ({meaning})",
    ]
    return "\n".join(lines) + "\n"
