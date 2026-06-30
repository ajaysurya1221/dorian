# Dorian Governance Data Model (v1.4)

*The concrete records the governance-foundation slice reads and writes. Every field here is
either deterministic input or human-authored context — none of it is a model summary, and none
of the prose fields ever decide a verdict.*

> **Status:** v1.4 (`[Unreleased]`). Additive only — no existing warrant, checker, exit code,
> fold policy, or security posture changed. Provenance sidecars are **deferred to v1.5**; the
> pane/TUI and a generic provider abstraction are **not** part of this model yet.

---

## 1. What's in this model, and what is deliberately not

v1.4 adds three durable record types and one ephemeral runtime file:

| Record | Path | Written by | Tracked in git? |
|---|---|---|---|
| **Goal** | `.dorian/goals/<goal_id>.goal.json` | `dorian goal add` | yes (a repo can commit its goals) |
| **Warrant** (unchanged) | `<artifact>.warrant` | `dorian seal`/`verify` | yes |
| **Gate decision packet** | stdout of `dorian gate` (not persisted by core) | `dorian gate` | n/a — emitted, not stored |
| **Last-decision packet** | `.dorian/local/last-decision.json` | the SubagentStop **host hook** | **no** — ephemeral, gitignored |

Two hard exclusions, stated up front because the whole design depends on them:

- **The `Warrant` schema is frozen.** `Warrant.compute_id` is `sha256` over the canonical body.
  Governance never adds a field to `Warrant`; new concepts become sibling sidecars under
  `.dorian/` with their own `schema_version`.
- **No prose feeds a verdict.** `Goal.statement` (and any other free-text field) is human context
  only. It is never sent to a model and never read by coverage or gate logic.

---

## 2. Goal record — `.dorian/goals/<goal_id>.goal.json`

A **human-authored** objective plus a **structural** coverage contract. Created by
`dorian goal add`; read by `dorian goal show` / `dorian goal check`.
(`src/dorian/goals.py`, `schema_version = 1`.)

| Field | Type | Role | Default |
|---|---|---|---|
| `goal_id` | `str` | identity; also the sidecar filename | — (required) |
| `title` | `str` | short human title | — (required) |
| `statement` | `str` | **human prose only — never fed to a model, never in verdict/coverage logic** | `""` |
| `policy_ref` | `str` | which loop policy this goal expects | `"default-assist"` |
| `scope` | `tuple[str, ...]` | jurisdiction globs (fnmatch); **empty = all paths** | `()` |
| `deny_paths` | `tuple[str, ...]` | extra denied globs | `()` |
| `base_ref` | `str` | the ref changed paths are computed against | `"HEAD"` (CLI) |
| `coverage_contract` | `dict` | **structural** contract only (e.g. a minimum strength floor) — no prose | `{}` |
| `status` | `str` | lifecycle marker | `"open"` |
| `warrant_ids` | `tuple[str, ...]` | warrants associated with this goal | `()` |
| `schema_version` | `int` | record version | `1` |

**Load is strict.** `goals.load` raises `ValueError` on non-JSON, a non-object body, a missing
required field, or `schema_version != 1` — an unknown future version fails loudly rather than
being silently misread.

---

## 3. Sidecar writer guarantees (`src/dorian/sidecars.py`)

Every `.dorian/` record is written through one deterministic writer so two runs on the same input
produce byte-identical files:

- **Deterministic bytes:** `json.dumps(payload, sort_keys=True, indent=2) + "\n"`, UTF-8, `\n`
  newlines.
- **Atomic:** written to a same-directory temp file, then `os.replace()` — a reader never sees a
  partial file.
- **Path-safe:** `write_sidecar(repo, rel_path, payload)` rejects an absolute or empty `rel_path`;
  `ensure_within(base, target)` resolves both paths and raises `ValueError` if the target escapes
  the repo (it is a containment check for trusted repos, **not** a sandbox).

---

## 4. Coverage diff — what is authoritative, and what never is

`goals.coverage_diff(goal, changed_paths, warranted_paths) -> {"covered": [...], "uncovered": [...]}`
is a **pure, path-derived** function. `dorian goal check` calls it with:

- **`changed_paths`** — derived from git (`gitio.changed_paths(repo, since)`), default `--since HEAD~1`.
- **`warranted_paths`** — the artifact paths of the repo's current warrants (the warrant store).

It keeps the changed paths that fall **in scope** (fnmatch against `goal.scope`; empty scope = all)
and reports which of those are **not** covered by a warrant. With `--fail-on-uncovered`, a non-empty
`uncovered` list exits `4` (REVOKED) — otherwise it just reports.

**What coverage means, precisely:** "a changed, in-scope path has at least one warrant." It does
**not** mean the goal is achieved. `Goal.statement`, `coverage_contract` prose, model output, and
the pane UI **never** influence this result. Coverage is a deterministic *floor* ("did the agent at
least sworn-claim the files it touched?"), not a judgment of correctness or completion.

---

## 5. Gate decision packet — `dorian gate` (stdout)

`dorian gate` reads a tool-call JSON on stdin, runs the **same pure loop preflight** as
`dorian loop preflight`, and prints the decision packet via `loop.render_json`
(`json.dumps(..., indent=2, sort_keys=True)`). The packet is the public, host-mappable contract:

| Key | Meaning |
|---|---|
| `schema_version` | packet version (`1`) |
| `decision` | one of `continue` · `repair` · `escalate` |
| `reason`, `loop_instruction` | human-readable steering text |
| `policy` | the effective policy (`cautious`/`assist`/`unattended`) |
| `candidates` | number of warrants considered |
| `trust_summary` | counts: `trusted`/`warranted`/`degraded`/`revoked`/`errored` |
| `broken_claims[]` | per broken claim: `artifact`, `claim_id`, `kind`, `load_bearing`, `verdict`, `paths`, `sensitive`, `in_scope`, `suggested_next_step`, … |
| `human_escalation` | `{required, reason, message}` |
| `repair` | `{attempts, max}` |
| `scope`, `sensitive_globs`, `notes` | the inputs echoed for the host |

**Exit codes from `dorian gate` are only `0` or `4`** (mapped from `decision` by `--fail-on
{never|repair|escalate}`, default `never`), plus `2` for malformed stdin. The gate **never** exits
`2` as a REPAIR/ESCALATE veto and **never** reads a clock or a nonce — those belong to the host
adapter (see §6 and `docs/SECURITY_BOUNDARY.md`). The verdict path is pure, deterministic, and
model-free.

---

## 6. Ephemeral host-hook state — `.dorian/local/last-decision.json`

This file is the **only** place wall-clock time and run identity enter the picture, and it is owned
entirely by the Claude Code adapter's host hooks — never by `dorian gate` or the core.

- **Written by** the `SubagentStop` hook (`dorian_loop_preflight.py`): it shells `dorian gate`,
  accepts return codes `0`/`4`, and persists the packet **augmented with host-stamped fields**.
- **Read by** the `PreToolUse` veto hook (`dorian_preflight_veto.py`) to decide whether to block a
  mutating tool call.

Host-stamped fields (added by the hook, **not** in the gate's pure output):

| Field | Source |
|---|---|
| `created_at_epoch` | `int(time.time())` — freshness; a packet older than `FRESH_SECONDS = 900` is stale |
| `repo_root` | `DORIAN_REPO_ROOT` or `os.getcwd()` |
| `base_ref` | `DORIAN_BASE` |
| `nonce` | `DORIAN_NONCE` (empty string if unset) |

`.dorian/local/` is **gitignored** and ephemeral: deleting it costs nothing, and its absence under a
strict policy is treated as *fail-closed* (no fresh decision ⇒ block), while under an attended policy
it *fails open* (a human is present). A **strict** policy is `DORIAN_POLICY=unattended` or
`DORIAN_EFFORT=godmode`; an **attended** policy is `cautious`/`assist` (the default). It is runtime
state, never an authoritative ledger — the core never reads it back into a verdict.

---

## 7. Authoritative vs. advisory — the one-glance table

| Influences a Dorian verdict? | Records / fields |
|---|---|
| **Yes — authoritative, deterministic** | warrant bodies & ids; checker results; `coverage_diff` over git-changed paths ∩ scope vs. warranted paths; the gate `decision` derived from revalidate + policy + scope + repair caps |
| **No — never touches truth** | `Goal.statement` and any prose; `coverage_contract` text; model summaries; the pane UI; `.dorian/local/last-decision.json` (runtime only); provenance sidecars (deferred, v1.5) |

---

## 8. Schema-version map

| Record | `schema_version` | Notes |
|---|---|---|
| `Warrant` | (frozen, content-addressed id) | never extended; new concepts = sibling sidecars |
| Goal | `1` | `src/dorian/goals.py` |
| Gate / loop decision packet | `1` | `src/dorian/loop.py` (`LoopDecision.to_dict`) |
| `.dorian/local/last-decision.json` | gate packet `1` + host-stamped fields | ephemeral; owned by the adapter |

New record types arrive as **new sibling sidecars with their own `schema_version`**, so the frozen
warrant schema and the existing exit-code/fold contracts stay untouched.

---

## See also

- `docs/SECURITY_BOUNDARY.md` — the core-vs-host-hook trust boundary and gate fail-closed behavior.
- `docs/DORIAN_PANE.md` — the future surface these records are designed to feed.
- `docs/DORIAN_LOOP_GUARD.md` — the loop preflight decision (`continue`/`repair`/`escalate`) the gate reuses.
- `docs/VALIDATION_HONESTY.md` — the trigger-vs-truth axes and the C4 determinism caveat.
