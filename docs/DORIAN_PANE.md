# Dorian Pane (vision)

*The "give your goal and go to sleep" surface. This document describes a **future** product
direction built on the deterministic primitives that ship in v1.4 — it is not a shipped feature,
and it makes no final design decisions.*

> **Status: deferred — NOT part of v1.4.** v1.4 ships the CLI spine (`dorian goal`, `dorian gate`)
> and a Claude Code hook adapter. The pane is the surface those records are *designed to feed* once
> built. **Claude Design owns the final TUI/pane design;** this doc only specifies the data
> contracts and product jobs behind it.

---

## What the pane is for

A long-running coding agent can churn for hours. Today a human reads scrollback to answer "is this
still on track, and do I need to step in?" The pane's job is to answer that from **deterministic
evidence** — warrants, coverage, and loop decisions — instead of from the agent's own narration.

"Give your goal and go to sleep" is a **product direction, not a guarantee.** What v1.4 actually
guarantees is narrow and real: a human-authored goal with a path-scoped coverage contract, a
deterministic gate that emits `continue`/`repair`/`escalate`, and a host adapter that can fail
closed under an unattended policy. The pane would make that loop *legible* — it does not make the
agent more autonomous than the underlying determinism allows.

## What the pane is **not**

- **Not a verdict author.** The pane *displays* deterministic results; it never computes trust,
  never runs a model, and never decides whether a goal is "done." Goal completion is **not**
  model-evaluated — coverage is a path-derived floor (see `docs/GOVERNANCE_DATA_MODEL.md`).
- **Not a sandbox or a security boundary.** It is a read-mostly viewer over the same records the
  CLI writes. Enforcement lives in the host hooks, not the UI.
- **Not multi-provider (yet).** v1.4 ships exactly one concrete adapter — Claude Code. The pane is
  described against that adapter; a generic provider abstraction is deferred until a second concrete
  adapter exists.

## The views (data jobs, not layouts)

Each view is defined by the **deterministic record it reads**. Layout, ordering, and visual
treatment are Claude Design's call.

| View | Question it answers | Source record (v1.4) |
|---|---|---|
| **Goal** | What did the human ask for, and under what policy? | `.dorian/goals/<id>.goal.json` (`title`, `statement`, `policy_ref`) |
| **Scope / denylist** | Which paths are in/out of jurisdiction? | `goal.scope`, `goal.deny_paths`; gate packet `scope`, `sensitive_globs` |
| **Warrants** | What has the agent sworn and proven? | `<artifact>.warrant` sidecars + the warrant store |
| **Coverage** | Which changed, in-scope paths are *not* yet warranted? | `goals.coverage_diff` → `{covered, uncovered}` |
| **Gate / loop decision** | Continue, repair, or escalate — and why? | gate packet: `decision`, `reason`, `loop_instruction`, `trust_summary`, `broken_claims[]` |
| **Repair** | How many repair attempts, against what cap? | gate packet `repair` `{attempts, max}` |
| **Escalation** | Does a human need to act, and on what? | gate packet `human_escalation` `{required, reason, message}` |
| **Host adapter state** | Is enforcement live, fresh, and identity-matched? | `.dorian/local/last-decision.json` (`created_at_epoch`, `repo_root`, `base_ref`, `nonce`); policy mode |

The **escalation** and **host adapter** views are where "go to sleep" earns or loses trust: they
must surface a stale packet, an identity mismatch, or a standing `escalate` *prominently*, because
under a strict policy those are exactly the states that fail closed.

## The deterministic data contract (what the pane may rely on)

Everything the pane renders comes from records this repo already writes deterministically:

- **Goal record** — `schema_version: 1`, byte-stable JSON (`docs/GOVERNANCE_DATA_MODEL.md` §2).
- **Gate decision packet** — `schema_version: 1`, the stdout of `dorian gate`, model-free and
  clock-free (§5). The pane reads this as the single source of "what should happen next."
- **Last-decision packet** — `.dorian/local/last-decision.json`, the gate packet plus host-stamped
  freshness/identity fields, **ephemeral and gitignored** (§6). The pane treats it as *runtime
  state*, never as history.

The pane must not invent fields or persist its own authoritative state; if it needs history, that is
a future record type (a sibling sidecar with its own `schema_version`), not a mutation of the frozen
warrant schema.

---

## Claude Design handoff

**Ownership.** Dorian/Opus owns the deterministic data contracts and the governance invariants
(what is true, what may influence a verdict, what fails open vs. closed). **Claude Design owns the
final pane/TUI design** — layout, information hierarchy, typography, color, interaction model, and
component choices. Nothing in this doc fixes those decisions.

**Data Claude Design can rely on being available.** The eight views above, each backed by the cited
record. All of it is local, deterministic, and already produced by the v1.4 CLI/adapter — no new
verification path is required to build the pane.

**Failure states the design must represent first-class** (not as afterthoughts):

- **No fresh decision** — `.dorian/local/last-decision.json` missing or older than the freshness
  window (`FRESH_SECONDS = 900`). Under a strict policy this *fails closed*; the pane must make that
  obvious, not silent.
- **Identity mismatch** — packet `repo_root`/`base_ref`/`nonce` disagree with the current run.
- **Standing escalate** — a decision the agent cannot self-clear; needs a human.
- **Degraded/errored claims** — `trust_summary` non-zero `degraded`/`errored`; a verdict exists but
  is weaker than "all green."

**Accessibility requirements** (constraints, not designs): decisions must be distinguishable without
relying on color alone (the three decisions and the fail-open/closed state each need a non-color
signal); all evidence must be reachable as text for screen readers and for copy-into-a-bug-report;
the pane must remain legible in a plain terminal.

**Decisions explicitly deferred to Claude Design:** the actual layout and navigation; how much
evidence to show inline vs. on demand; live-tail vs. snapshot refresh model; how repair/escalation
history is visualized; any keyboard/interaction grammar.

---

## See also

- `docs/GOVERNANCE_DATA_MODEL.md` — the exact records and fields the pane reads.
- `docs/DORIAN_LOOP_GUARD.md` — the `continue`/`repair`/`escalate` decision the pane surfaces.
- `docs/SECURITY_BOUNDARY.md` — why enforcement lives in the host hooks, not the pane.
