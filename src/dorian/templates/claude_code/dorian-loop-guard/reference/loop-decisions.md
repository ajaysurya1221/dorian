# Loop decisions: continue / repair / escalate

`dorian loop preflight` runs `dorian revalidate` (deterministic, token-free) on the
warrants the change touched, then classifies the result. The decision is a **pure
function** of the revalidate outcome, the policy, the repair-attempt count, and the
scope/denylist — no model, same input → same decision.

## Decision precedence (first match wins)

| # | Condition | Decision |
|---|-----------|----------|
| 1 | A checker **ERRORED** (could not run) | **escalate** (`fix_environment`) |
| 2 | A break exists **and** `repair_attempts >= max_repairs` | **escalate** (infinite-fix cap) |
| 3 | A broken/errored claim is bound to a **sensitive / denylisted** path | **escalate** |
| 4 | A **load-bearing** break is **outside `--scope`** | **escalate** (over-reach) |
| 5 | `unattended` policy **and no `--scope`** configured, with a load-bearing break | **escalate** |
| 6 | A **load-bearing** break, in scope, under the cap | **repair** |
| 7 | Only **non-load-bearing** breaks (DEGRADED) | `cautious`: **repair** · else **continue** (warn) |
| 8 | No breaks (TRUSTED, or no warranted claim touched) | **continue** |

`max_repairs` defaults per policy (cautious 1, assist/unattended 3) unless `--max-repairs`
overrides. The active sensitive-path set (built-in security/infra/secrets/CI globs plus
any `--deny-path`) is echoed in the packet's `sensitive_globs`, so it is never hidden.

## Policies

- **cautious** — most conservative. Repairs even non-load-bearing breaks; cap 1. Use when
  a human is watching closely.
- **assist** (default) — repairs load-bearing breaks; continues past non-load-bearing
  breaks with a warning; cap 3. Use for assisted loops.
- **unattended** — same break handling as assist, but a load-bearing break **escalates
  unless `--scope` is set** (an L3 unattended loop needs a bounded lane). Cap 3.

## Per-claim next step (`suggested_next_step`)

A hint, not a verdict — Dorian cannot know your intent:

- `repair_code` — the code drifted from a still-true claim; fix the smallest cause.
- `update_claim` — the change was intentional; update the claim/doc instead of the code.
- `fix_environment` — the checker **ERRORED**; fix the environment/infra, do not weaken
  the checker.
- `escalate` — this specific claim triggered the escalation (sensitive path, over-reach,
  or the cap).

## Exit codes

`dorian loop preflight` exits **0 on success regardless of the decision** — Dorian does
not stop the loop by default; the decision is in the output. For a hard CI gate, opt in
with `--fail-on repair` or `--fail-on escalate` (exit 4 at/above that severity). Corrupt
sidecar / bad input follow the usual contract (2 usage, 4 integrity).

## Loop-engineering failure modes

Dorian is the deterministic verifier *underneath* an LLM verifier sub-agent; it maps onto
the loop-engineering failure catalog as follows. Dorian provides the **signal**; delivery,
scheduling, and budgeting stay with the loop runner.

| Failure mode | Dorian helps? | How |
|---|---|---|
| Weak verification / same-session verifier | **strongly** | Dorian is, by construction, a separate model-free verifier that cannot rubber-stamp. |
| Verifier theater ("looks good", no tests) | **strongly** | A warrant either matches or REVOKEs, leaving an inspectable sidecar — it cannot just approve. |
| Infinite fix loop | **signal** | Repeated REVOKED across attempts + the `--max-repairs` cap → escalate. The attempt *counter* lives in your STATE.md. |
| Escalation failure | **trigger** | A revoked/errored load-bearing claim is an unambiguous escalate trigger. **Delivery** (Slack/STATE.md "waiting on human") is the loop runner's job. |
| Over-reach / wrong scope | **partial** | `--scope` escalates a break outside the lane; warrants catch a silently-mutated fact. Path allow/deny enforcement stays in your skills/safety config. |
| State rot | **partial** | Code-anchored warrants auto-REVOKE on drift instead of rotting. Live PR/ticket liveness is the loop runner's prune step. |
| Token burn | **aligned** | Token-free preflight is a cheap "is anything actually broken?" pre-filter before spawning expensive sub-agents. Budget caps stay with loop-cost. |
| Comprehension debt | **partial** | The warrant ledger is machine-checked documentation of what is guaranteed. Does not replace human review. |
| Notification fatigue | **marginal** | Deterministic verdicts are high-precision escalation triggers (fewer false pings). Routing/digest is the loop runner's. |
| Parallel collision | **no** | Worktree isolation / branch locks are the loop runner's job. Dorian defers. |
| Cognitive surrender | **cultural** | Writing explicit claims is stating intent, but human gates are process, not Dorian. |
