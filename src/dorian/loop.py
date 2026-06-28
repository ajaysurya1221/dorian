"""dorian loop: deterministic CONTINUE / REPAIR / ESCALATE steering for AI coding loops.

Loop Guard is a thin classifier ON TOP OF ``revalidate``. It re-checks the claim
warrants a change touched, reads their post-fold trust state, and turns that
deterministic verdict into a loop *decision packet*: continue the loop, repair a
broken load-bearing claim, or escalate to a human. **No model runs here** — the
verdict is exactly ``revalidate``'s, so Loop Guard is token-free and inherits the
protocol's trigger-vs-truth discipline: a ``REVOKED`` claim is a steering signal,
an ``ERRORED`` checker is fail-closed evidence — neither is a verdict on the whole
loop, and neither is a "moral failure".

What Loop Guard is NOT: it does not judge whole-loop success, run the loop,
schedule it, manage worktrees, deliver notifications, or estimate token cost —
those belong to the loop runner (e.g. loop-engineering's loop-init / loop-audit /
loop-cost). Loop Guard is the deterministic *truth layer* the loop's verifier step
stands on. It is **not a sandbox** (``C4 pytest:``/``C5 shell:`` checkers execute
code through ``revalidate``); use it on trusted repos.

The install scaffolder reuses ``claude_code``'s file machinery with a Loop-Guard
manifest, so the ``.claude/skills/dorian-loop-guard/`` bundle ships as package data.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, replace
from pathlib import Path

from dorian import store
from dorian.claude_code import _Template
from dorian.model import Warrant
from dorian.policy import ExecutionPolicy
from dorian.revalidate import RevalResult, revalidate

SCHEMA_VERSION = 1

POLICIES = ("cautious", "assist", "unattended")
DEFAULT_POLICY = "assist"
# Per-policy default repair-attempt cap (an explicit --max-repairs overrides). Cautious
# escalates sooner; assist/unattended allow a few autonomous repair iterations.
_DEFAULT_MAX_REPAIRS = {"cautious": 1, "assist": 3, "unattended": 3}

DECISIONS = ("continue", "repair", "escalate")
NEXT_STEPS = ("repair_code", "update_claim", "fix_environment", "escalate")

# Built-in sensitive-path globs (fnmatch, '*' crosses '/'): a broken or errored claim
# touching one of these ESCALATES under every policy — security/infra/secrets/CI changes
# want a human, not an autonomous repair. The active set (these plus any --deny-path) is
# echoed in the packet's `sensitive_globs`, so the heuristic is transparent, never hidden.
SENSITIVE_GLOBS = (
    "*secret*",
    "*.pem",
    "*.key",
    "*.env",
    "*.env.*",
    ".github/workflows/*",
    "*Dockerfile*",
    "*/secrets/*",
    "*/auth/*",
    "*/security/*",
    "*/migrations/*",
    "infra/*",
    "deploy/*",
    "terraform/*",
    "*.tf",
)


@dataclass(frozen=True)
class BrokenClaim:
    """One re-checked claim that did not hold this run (BROKEN) or could not run
    (ERRORED), enriched with the steering metadata the next iteration needs."""

    artifact: str
    warrant: str  # warrant id
    claim_id: str
    text: str
    kind: str
    load_bearing: bool
    verdict: str  # BROKEN | ERRORED
    trust_state: str  # the warrant's post-fold trust state (REVOKED|DEGRADED|UNKNOWN|...)
    checker: str  # checker type, e.g. C3 / C4 / C5
    evidence: str  # revalidate detail (why it broke / why it errored)
    paths: tuple[str, ...]  # files the claim is bound to (checker watches + supports)
    sensitive: bool
    in_scope: bool
    suggested_next_step: str  # one of NEXT_STEPS

    def to_dict(self) -> dict:
        return {
            "artifact": self.artifact,
            "warrant": self.warrant,
            "claim_id": self.claim_id,
            "text": self.text,
            "kind": self.kind,
            "load_bearing": self.load_bearing,
            "verdict": self.verdict,
            "trust_state": self.trust_state,
            "checker": self.checker,
            "evidence": self.evidence,
            "paths": list(self.paths),
            "sensitive": self.sensitive,
            "in_scope": self.in_scope,
            "suggested_next_step": self.suggested_next_step,
        }


@dataclass(frozen=True)
class LoopDecision:
    """The deterministic loop-steering packet: a pure function of the RevalResult,
    the policy, the repair-attempt count, and the scope/denylist."""

    decision: str  # continue | repair | escalate
    reason: str
    policy: str
    candidates: int
    trust_summary: dict
    broken_claims: tuple[BrokenClaim, ...]
    recalled: tuple[dict, ...]
    loop_instruction: str
    human_escalation: dict
    repair: dict  # {"attempts": int, "max": int}
    scope: tuple[str, ...]
    sensitive_globs: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": self.decision,
            "reason": self.reason,
            "policy": self.policy,
            "candidates": self.candidates,
            "trust_summary": dict(sorted(self.trust_summary.items())),
            "broken_claims": [b.to_dict() for b in self.broken_claims],
            "recalled": [dict(r) for r in self.recalled],
            "loop_instruction": self.loop_instruction,
            "human_escalation": self.human_escalation,
            "repair": self.repair,
            "scope": list(self.scope),
            "sensitive_globs": list(self.sensitive_globs),
            "notes": list(self.notes),
        }


def _matches_any(path: str, globs: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _claim_paths(claim, entries: dict) -> tuple[str, ...]:
    """Files a claim is bound to: every checker watch plus every supported read-set uri."""
    paths: set[str] = set()
    for spec in claim.checkers:
        paths.update(spec.watch)
    for sid in claim.supports:
        e = entries.get(sid)
        if e is not None:
            paths.add(e.uri)
    return tuple(sorted(paths))


def _split_detail(detail: str) -> tuple[str | None, str]:
    """Split a revalidate detail into (checker_type, evidence). A BROKEN detail is
    prefixed ``C3: ...`` — return ("C3", the rest); an ERRORED detail has no prefix —
    return (None, detail). Splitting it out keeps the checker type and the evidence
    separate so renderers don't double the prefix (``C3: C3: ...``)."""
    head = detail.split(":", 1)[0].strip()
    if len(head) == 2 and head[0] == "C" and head[1].isdigit():
        return head, detail.split(":", 1)[1].strip()
    return None, detail


def _warrant_states(repo: Path) -> dict:
    """{warrant_id: trust_state} for every indexed warrant. Read after ``revalidate``
    has synced + folded + committed, so these are the post-fold trust states."""
    conn = store.connect(repo)
    try:
        return {w["id"]: w["trust_state"] for w in store.get_warrants(conn)}
    finally:
        conn.close()


_STATE_TO_BUCKET = {
    "TRUSTED": "trusted",
    "WARRANTED": "warranted",
    "DEGRADED": "degraded",
    "REVOKED": "revoked",
    "UNKNOWN": "errored",  # a checker ERRORED -> warrant folds to UNKNOWN -> count as errored
}


def _trust_summary(result: RevalResult, states: dict) -> dict:
    """Bucketed counts of the TOUCHED warrants' post-fold trust states."""
    buckets = {"trusted": 0, "warranted": 0, "degraded": 0, "revoked": 0, "errored": 0}
    touched = (
        set(result.artifacts)
        | {wid for wid, _, _ in result.broken}
        | {wid for wid, _, _ in result.errored}
    )
    for wid in touched:
        bucket = _STATE_TO_BUCKET.get(states.get(wid, ""))
        if bucket:
            buckets[bucket] += 1
    return buckets


def _collect_broken(
    repo: Path,
    result: RevalResult,
    states: dict,
    scope: tuple[str, ...],
    sensitive_globs: tuple[str, ...],
) -> tuple[list[BrokenClaim], list[str]]:
    """Enrich every BROKEN/ERRORED record with claim text/kind/load_bearing/paths and
    the sensitive/in-scope flags. Returns (broken_claims, notes). The provisional
    suggested_next_step is set here (fix_environment for ERRORED, repair_code for BROKEN);
    `_decide` may upgrade specific ones to `escalate`."""
    notes: list[str] = []
    cache: dict[str, Warrant | None] = {}

    def warrant_for(wid: str) -> Warrant | None:
        if wid not in cache:
            uri = result.artifacts.get(wid)
            try:
                cache[wid] = Warrant.load(repo / (uri + ".warrant")) if uri else None
            except Exception:  # sidecar already integrity-checked by revalidate; stay robust
                cache[wid] = None
        return cache[wid]

    out: list[BrokenClaim] = []
    for verdict, recs in (("BROKEN", result.broken), ("ERRORED", result.errored)):
        for wid, cid, detail in recs:
            w = warrant_for(wid)
            artifact = result.artifacts.get(wid, "")
            claim = next((c for c in w.claims if c.id == cid), None) if w else None
            step = "fix_environment" if verdict == "ERRORED" else "repair_code"
            ctype, evidence = _split_detail(detail)
            if claim is None:
                notes.append(f"{cid}: claim unreadable from {artifact}.warrant; using bare record")
                out.append(
                    BrokenClaim(
                        artifact=artifact,
                        warrant=wid,
                        claim_id=cid,
                        text="",
                        kind="",
                        load_bearing=True,  # fail-safe: treat unknown as load-bearing
                        verdict=verdict,
                        trust_state=states.get(wid, ""),
                        checker=ctype or "",
                        evidence=evidence,
                        paths=(),
                        sensitive=False,
                        in_scope=True,
                        suggested_next_step=step,
                    )
                )
                continue
            entries = {e.id: e for e in w.read_set}
            paths = _claim_paths(claim, entries)
            sensitive = any(_matches_any(p, sensitive_globs) for p in paths)
            in_scope = True if not scope else all(_matches_any(p, scope) for p in paths)
            out.append(
                BrokenClaim(
                    artifact=artifact,
                    warrant=wid,
                    claim_id=cid,
                    text=claim.text,
                    kind=claim.kind,
                    load_bearing=bool(claim.load_bearing),
                    verdict=verdict,
                    trust_state=states.get(wid, ""),
                    checker=ctype or (claim.checkers[0].type if claim.checkers else ""),
                    evidence=evidence,
                    paths=paths,
                    sensitive=sensitive,
                    in_scope=in_scope,
                    suggested_next_step=step,
                )
            )
    return out, notes


def _decide(
    broken: list[BrokenClaim],
    result: RevalResult,
    *,
    policy: str,
    max_repairs: int,
    repair_attempts: int,
    scope_given: bool,
) -> tuple[str, str, str]:
    """Pure decision over the enriched breaks. Returns (decision, reason, cause).

    Precedence (first match wins): errored -> cap -> sensitive -> over-reach ->
    unattended-needs-scope -> repair (load-bearing) -> degraded (non-load-bearing) ->
    continue. `cause` keys the per-claim next-step assignment in `_assign_steps`."""
    errored = [b for b in broken if b.verdict == "ERRORED"]
    breaks = [b for b in broken if b.verdict == "BROKEN"]
    lb = [b for b in breaks if b.load_bearing]
    nlb = [b for b in breaks if not b.load_bearing]

    if errored:
        return (
            "escalate",
            f"{len(errored)} checker(s) ERRORED (could not run) — fail-closed evidence, "
            "not a false claim; the environment/infra needs a human before the loop continues.",
            "errored",
        )
    # breaks the active policy would actually REPAIR: load-bearing always, plus
    # non-load-bearing under cautious. assist/unattended `continue` past a
    # non-load-bearing break, so the cap and over-reach guards must not stop the loop
    # for one (don't stop the loop unnecessarily).
    repairable = lb + (nlb if policy == "cautious" else [])
    if repairable and repair_attempts >= max_repairs:
        return (
            "escalate",
            f"repair attempt cap reached ({repair_attempts} >= {max_repairs}) — a claim the loop "
            "would repair is still broken after repeated attempts (possible infinite-fix loop).",
            "cap",
        )
    if any(b.sensitive for b in broken):
        return (
            "escalate",
            "a broken/errored claim is bound to a sensitive or denylisted path "
            "(security / infra / secrets / CI) — a human must review the repair.",
            "sensitive",
        )
    if scope_given and any(not b.in_scope for b in repairable):
        return (
            "escalate",
            "a claim the loop would repair broke outside the configured --scope (possible "
            "over-reach) — escalate rather than repair out of the loop's lane.",
            "scope",
        )
    if lb and policy == "unattended" and not scope_given:
        return (
            "escalate",
            "unattended policy requires a bounded --scope before autonomously repairing a "
            "load-bearing break (an L3 loop needs a denylist/scope) — escalate.",
            "unattended_no_scope",
        )
    if lb:
        return (
            "repair",
            f"{len(lb)} load-bearing claim(s) REVOKED, in scope and under the repair cap — "
            "repair the smallest cause (or update the claim/doc if the change was intentional).",
            "repair",
        )
    if nlb:
        if policy == "cautious":
            return (
                "repair",
                f"{len(nlb)} non-load-bearing claim(s) broke (DEGRADED); the cautious policy "
                "repairs them rather than continuing.",
                "degraded_repair",
            )
        return (
            "continue",
            f"{len(nlb)} non-load-bearing claim(s) broke (DEGRADED) — not blocking under the "
            f"{policy} policy; continue and address them when convenient.",
            "degraded_continue",
        )
    if result.candidates == 0:
        return (
            "continue",
            "no warranted claims were affected by the changed paths — nothing to steer on.",
            "clean",
        )
    return (
        "continue",
        f"all {result.candidates} re-checked claim(s) still hold — touched warrants are TRUSTED.",
        "clean",
    )


def _assign_steps(broken: list[BrokenClaim], *, cause: str) -> list[BrokenClaim]:
    """Finalize each claim's suggested_next_step given the overall escalation cause:
    the specific claims that triggered an escalation are marked `escalate`; ERRORED
    stays `fix_environment`; everything else stays `repair_code`."""
    out: list[BrokenClaim] = []
    for b in broken:
        step = b.suggested_next_step
        if b.verdict == "ERRORED":
            step = "fix_environment"
        elif (
            (cause == "sensitive" and b.sensitive)
            or (cause == "scope" and not b.in_scope)
            or (cause in ("cap", "unattended_no_scope") and b.verdict == "BROKEN")
        ):
            step = "escalate"
        out.append(replace(b, suggested_next_step=step))
    return out


def _loop_instruction(
    decision: str, reason: str, broken: list[BrokenClaim], max_repairs: int
) -> str:
    """A compact, agent-readable instruction for the next loop iteration."""
    if decision == "continue":
        return (
            "CONTINUE: no broken load-bearing claims for the changed paths. Proceed with the next "
            "planned step, stay within scope, and re-run `dorian loop preflight` next iteration."
        )
    if decision == "repair":
        # name only in-scope breaks: an out-of-scope load-bearing break would have
        # ESCALATED, so a repair instruction must never tell the agent to touch a file
        # outside the configured lane (a co-occurring out-of-scope non-load-bearing break
        # can ride along under assist).
        focus = [b for b in broken if b.in_scope] or broken
        ids = ", ".join(f"{b.claim_id} ({b.artifact})" for b in focus) or "(none)"
        paths = sorted({p for b in focus for p in b.paths})
        return (
            f"REPAIR: fix the smallest cause of these broken claim(s): {ids}. "
            f"Touch only: {', '.join(paths) or 'the bound files'}. Re-run the exact checker or "
            "`dorian revalidate --since <base>` to confirm. If the change was intentional, update "
            f"the claim/doc instead of the code. Do not exceed {max_repairs} repair attempt(s) — "
            "escalate after that."
        )
    # escalate: the human sees every broken/errored claim, in or out of scope
    ids = ", ".join(f"{b.claim_id} ({b.artifact})" for b in broken) or "(none)"
    paths = sorted({p for b in broken for p in b.paths})
    return (
        f"ESCALATE: stop autonomous edits. {reason} Hand off to a human with the broken claim(s): "
        f"{ids}; evidence and bound files: {', '.join(paths) or '(none)'}. "
        "Record this in STATE.md under 'waiting on human'."
    )


def preflight(
    repo: Path,
    *,
    since: str | None = None,
    changed_paths_file: Path | None = None,
    policy: str = DEFAULT_POLICY,
    max_repairs: int | None = None,
    repair_attempts: int = 0,
    scope: tuple[str, ...] = (),
    deny_paths: tuple[str, ...] = (),
    exec_policy: ExecutionPolicy | None = None,
    checker_source: str = "head",
    enable_c2lite: bool = False,
    extra_notes: tuple[str, ...] = (),
) -> LoopDecision:
    """Re-check the warrants the change touched and classify the result into a
    CONTINUE/REPAIR/ESCALATE decision packet. Pure verdict reuse — calls
    ``revalidate`` (token-free, deterministic) and never runs a model.

    One of ``since`` or ``changed_paths_file`` is required (as for ``revalidate``).
    ``policy`` is one of POLICIES; ``max_repairs`` defaults per-policy when None."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
    cap = _DEFAULT_MAX_REPAIRS[policy] if max_repairs is None else max_repairs
    sensitive_globs = SENSITIVE_GLOBS + tuple(deny_paths)

    result = revalidate(
        repo,
        since=since,
        changed_paths_file=changed_paths_file,
        enable_c2lite=enable_c2lite,
        policy=exec_policy if exec_policy is not None else ExecutionPolicy(),
        checker_source=checker_source,
    )
    states = _warrant_states(repo)
    broken, notes = _collect_broken(repo, result, states, scope, sensitive_globs)
    notes = list(extra_notes) + notes
    if result.notes:  # checker-source=base advisories from revalidate
        notes.extend(result.notes)

    decision, reason, cause = _decide(
        broken,
        result,
        policy=policy,
        max_repairs=cap,
        repair_attempts=repair_attempts,
        scope_given=bool(scope),
    )
    broken = _assign_steps(broken, cause=cause)
    instruction = _loop_instruction(decision, reason, broken, cap)
    human = {
        "required": decision == "escalate",
        "reason": reason if decision == "escalate" else "",
        "message": instruction if decision == "escalate" else "",
    }
    if result.recalled:
        n = len({e["warrant_id"] for e in result.recalled})
        notes.append(f"{n} downstream warrant(s) recalled (flagged, not re-checked).")

    return LoopDecision(
        decision=decision,
        reason=reason,
        policy=policy,
        candidates=result.candidates,
        trust_summary=_trust_summary(result, states),
        broken_claims=tuple(broken),
        recalled=tuple(result.recalled),
        loop_instruction=instruction,
        human_escalation=human,
        repair={"attempts": repair_attempts, "max": cap},
        scope=tuple(scope),
        sensitive_globs=sensitive_globs,
        notes=tuple(notes),
    )


# --- repair-attempt state ----------------------------------------------------------


def read_repair_attempts(path: Path) -> tuple[int, str | None]:
    """Read ``repair_attempts`` (int) from a JSON state file. Returns (count, note):
    a missing/unreadable/garbled file yields (0, note) — never raises, so a fresh loop
    with no state file just starts at zero."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 0, f"--state-file unreadable ({exc}); assuming repair_attempts=0"
    value = data.get("repair_attempts", 0) if isinstance(data, dict) else 0
    try:
        return max(0, int(value)), None
    except (TypeError, ValueError):
        return 0, "--state-file repair_attempts is not an integer; assuming 0"


# --- renderers (all operate on packet.to_dict()) -----------------------------------


def render_json(d: dict) -> str:
    return json.dumps(d, indent=2, sort_keys=True) + "\n"


_DECISION_GLYPH = {"continue": "▶ CONTINUE", "repair": "✎ REPAIR", "escalate": "⚠ ESCALATE"}
_SUMMARY_KEYS = ("trusted", "warranted", "degraded", "revoked", "errored")


def render_text(d: dict) -> str:
    lines = [f"decision: {d['decision'].upper()}  (policy={d['policy']})", f"  {d['reason']}"]
    ts = d["trust_summary"]
    lines.append("  trust: " + " ".join(f"{k}={ts[k]}" for k in _SUMMARY_KEYS))
    for b in d["broken_claims"]:
        lb = "load-bearing" if b["load_bearing"] else "non-load-bearing"
        lines.append(f"  {b['verdict']:7} {b['claim_id']}  [{lb}]  {b['checker']}: {b['evidence']}")
        paths = ", ".join(b["paths"]) or "-"
        lines.append(f"          paths={paths}  -> {b['suggested_next_step']}")
    if d["human_escalation"]["required"]:
        lines.append(f"  human escalation REQUIRED: {d['human_escalation']['reason']}")
    for note in d["notes"]:
        lines.append(f"  note: {note}")
    lines.append(f"  next: {d['loop_instruction']}")
    return "\n".join(lines) + "\n"


def render_md(d: dict) -> str:
    glyph = _DECISION_GLYPH.get(d["decision"], d["decision"].upper())
    lines = [
        f"### dorian loop: {glyph}",
        "",
        f"**Decision:** `{d['decision']}` · **policy:** `{d['policy']}` · "
        f"**repair:** {d['repair']['attempts']}/{d['repair']['max']}",
        "",
        d["reason"],
    ]
    ts = d["trust_summary"]
    lines += [
        "",
        "| " + " | ".join(_SUMMARY_KEYS) + " |",
        "| " + " | ".join(["---:"] * len(_SUMMARY_KEYS)) + " |",
        "| " + " | ".join(str(ts[k]) for k in _SUMMARY_KEYS) + " |",
    ]
    if d["broken_claims"]:
        lines += [
            "",
            "| claim | artifact | kind | load-bearing | verdict | why | next |",
            "| --- | --- | --- | :---: | --- | --- | --- |",
        ]
        for b in d["broken_claims"]:
            why = f"{b['checker']}: {b['evidence']}".replace("|", "\\|")[:160]
            lines.append(
                f"| `{b['claim_id']}` | `{b['artifact']}` | {b['kind']} | "
                f"{'yes' if b['load_bearing'] else 'no'} | {b['verdict']} | {why} | "
                f"{b['suggested_next_step']} |"
            )
    if d["human_escalation"]["required"]:
        lines += ["", f"> **Human escalation required.** {d['human_escalation']['reason']}"]
    if d["notes"]:
        lines += ["", "Notes:"] + [f"- {n}" for n in d["notes"]]
    lines += ["", f"**Next iteration:** {d['loop_instruction']}"]
    return "\n".join(lines) + "\n"


def render_prompt(d: dict) -> str:
    """A compact markdown prompt for the next coding-agent iteration."""
    header = {
        "continue": "Dorian Loop Guard says CONTINUE.",
        "repair": "Dorian Loop Guard says REPAIR before continuing.",
        "escalate": "Dorian Loop Guard says ESCALATE — stop autonomous edits.",
    }[d["decision"]]
    lines = [f"# {header}", "", d["loop_instruction"], ""]
    if d["broken_claims"]:
        lines.append("Broken / unrunnable claims:")
        for b in d["broken_claims"]:
            tag = "load-bearing" if b["load_bearing"] else "non-load-bearing"
            lines.append(
                f"- `{b['claim_id']}` in `{b['artifact']}` ({tag}, {b['verdict']}): "
                f"{b['text'] or '(claim text unavailable)'}"
            )
            lines.append(f"  - why: {b['checker']}: {b['evidence']}")
            lines.append(
                f"  - bound files: {', '.join(b['paths']) or '(none)'} → "
                f"suggested: {b['suggested_next_step']}"
            )
    lines += [
        "",
        "Boundary: Dorian verified only these specific warranted claims, not the whole loop. "
        "REVOKED is a steering signal, not a moral failure; ERRORED is fail-closed evidence, not a "
        "false claim. Dorian is not a sandbox — trusted repos only.",
    ]
    return "\n".join(lines) + "\n"


# --- install scaffolder (reuses claude_code.build_plan/apply with a Loop-Guard manifest) ---

SKILL_DIR = ".claude/skills/dorian-loop-guard"
# logical groups: "skill" installs by default; "state" (LOOP.md/STATE.md/run-log at the
# repo root) and "action" (a GitHub Actions example) are opt-in.
GROUPS = ("skill", "state", "action")
DEFAULT_GROUPS = frozenset({"skill"})

LOOP_MANIFEST: tuple[_Template, ...] = (
    _Template(
        "dorian-loop-guard/SKILL.md",
        f"{SKILL_DIR}/SKILL.md",
        "skill",
        "the skill, invoked as /dorian-loop-guard",
    ),
    _Template(
        "dorian-loop-guard/README.md",
        f"{SKILL_DIR}/README.md",
        "skill",
        "what the bundle is and how to use it",
    ),
    _Template(
        "dorian-loop-guard/reference/loop-decisions.md",
        f"{SKILL_DIR}/reference/loop-decisions.md",
        "skill",
        "continue / repair / escalate, and the policies",
    ),
    _Template(
        "dorian-loop-guard/reference/safety-boundary.md",
        f"{SKILL_DIR}/reference/safety-boundary.md",
        "skill",
        "Dorian steers, it does not judge the loop; not a sandbox",
    ),
    _Template(
        "dorian-loop-guard/templates/LOOP.md",
        f"{SKILL_DIR}/templates/LOOP.md",
        "skill",
        "example loop spec (copy to repo root)",
    ),
    _Template(
        "dorian-loop-guard/templates/STATE.md",
        f"{SKILL_DIR}/templates/STATE.md",
        "skill",
        "example live loop state (copy to repo root)",
    ),
    _Template(
        "dorian-loop-guard/templates/loop-run-log.md",
        f"{SKILL_DIR}/templates/loop-run-log.md",
        "skill",
        "example append-only run log",
    ),
    _Template(
        "dorian-loop-guard/templates/dorian-loop.yml",
        f"{SKILL_DIR}/templates/dorian-loop.yml",
        "skill",
        "example GitHub Actions preflight step",
    ),
    # opt-in: write the live state files to the repo root (--with-state)
    _Template("dorian-loop-guard/templates/LOOP.md", "LOOP.md", "state", "loop spec at repo root"),
    _Template("dorian-loop-guard/templates/STATE.md", "STATE.md", "state", "live loop state"),
    _Template(
        "dorian-loop-guard/templates/loop-run-log.md",
        "loop-run-log.md",
        "state",
        "append-only run log",
    ),
    # opt-in: a GitHub Actions example workflow (--with-action)
    _Template(
        "dorian-loop-guard/templates/dorian-loop.yml",
        ".github/workflows/dorian-loop.yml",
        "action",
        "GitHub Actions loop preflight workflow",
    ),
)

NEXT_STEPS_INSTALL = (
    "Restart Claude Code (a new skills directory registers only at startup)",
    "Before each loop iteration, run:  dorian loop preflight --since <base> --format json",
    "Act on the decision: CONTINUE / REPAIR / ESCALATE (see the printed loop_instruction)",
    "After a change, seal new warrants with /dorian-claim-warrants, then `dorian verify`",
    "Copy templates/LOOP.md + STATE.md to the repo root (or re-run with --with-state)",
)

TRUST_BOUNDARY = (
    "Loop Guard steers; it does not judge whole-loop success and runs no model at check time. "
    "REVOKED is a steering signal, ERRORED is fail-closed evidence. Not a sandbox — trusted repos."
)
