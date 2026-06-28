# Loop-engineering alignment

How Dorian Loop Guard plugs into [loop-engineering](https://github.com/cobusgreyling/loop-engineering)
(MIT) — and, just as importantly, where it deliberately does **not** compete. Loop
engineering frames building autonomous agent loops out of primitives (scheduling,
run-until-done, worktrees, skills, connectors/MCP, sub-agents) plus durable memory, scored
by readiness levels L0→L3. Dorian is one primitive in that world: the **deterministic,
token-free verifier** under the maker/checker split.

> Treat loop-engineering as adjacent ecosystem and design inspiration; this is alignment,
> not a fork. Verify its facts live before relying on dated specifics.

## Primitive map

| loop-engineering primitive | Dorian's relationship |
|---|---|
| **Scheduling / automations** (`/loop`, cron, Actions) | Dorian runs *inside* a scheduled step; it never schedules. |
| **Run-until-done** (`/goal`) | A warrant's TRUSTED/REVOKED is a deterministic stop/continue input to the loop's condition. |
| **Worktrees** (isolation) | Dorian verifies inside a worktree; it does not manage them. |
| **Skills** | Dorian ships a skill (`/dorian-loop-guard`) and a verify step; complementary to project skills. |
| **Connectors / MCP** | Dorian is local + token-free; escalation *delivery* over connectors is the loop runner's. |
| **Sub-agents (maker/checker)** | Dorian is the deterministic floor under the *checker* role — it cannot grade its own work or rubber-stamp. |
| **Memory / state** (LOOP.md, STATE.md, run log) | `.warrant` sidecars are deterministic, revalidatable memory; Dorian *reads* a repair-attempt count, never writes loop state. |

## Readiness levels

- **L1 (report)** — `dorian loop preflight --format md|json` writes a deterministic finding
  to state; a human acts. Maps to the `cautious`/`assist` policies with `--fail-on never`.
- **L2 (assisted)** — `assist` policy: repair load-bearing breaks under a cap, continue past
  non-load-bearing. The `--max-repairs` cap + `--repair-attempts` accounting is the bounded
  auto-fix gate L2 requires.
- **L3 (unattended)** — `unattended` policy **requires `--scope`** before autonomously
  repairing a load-bearing break, mirroring L3's "denylist/bounded lane required" rule.
  Pair with `--state-file`, `--deny-path`, and explicit human escalation.

## Where Dorian plugs in

The deterministic verify step. Its decision maps directly onto the loop's gate:

- **CONTINUE** → commit / open PR / next planned step.
- **REPAIR** → hand the broken claim(s) back to the implementer (smallest cause).
- **ESCALATE** → write to STATE.md "waiting on human" and ping via a connector.

The `.warrant` trail complements `loop-run-log.md` as the deterministic-evidence ledger.

## Where Dorian should NOT compete

| loop-engineering tool | Why Dorian stays out |
|---|---|
| **loop-init** | Scaffolds loop starters/budget/run-log. Dorian *consumes* these files; `dorian loop install` only adds the verify skill + examples. |
| **loop-audit** | Scores L0–L3 readiness. Dorian can be *evidence* for a checklist item ("independent deterministic verifier present"), never a re-implementation of scoring. |
| **loop-cost** | Estimates token spend. Dorian is token-free and models no cost. |
| **schedulers / worktree managers** | Cadence, durability, isolation, parallel-collision locks — entirely the loop runner's. |

## Failure-mode coverage

| loop-engineering failure mode | Dorian | Note |
|---|---|---|
| Weak verification / same-session verifier | **strong** | model-free, separate-by-construction verifier |
| Verifier theater | **strong** | can't say "looks good" — REVOKE leaves a sidecar |
| Infinite fix loop | **signal + cap** | repeated REVOKED + `--max-repairs` → escalate; the *counter* lives in STATE.md |
| Escalation failure | **trigger** | unambiguous escalate trigger; **delivery** is the loop runner's |
| Over-reach / wrong scope | **partial** | `--scope` escalates out-of-lane breaks; path allow/deny stays in skills |
| State rot | **partial** | code-anchored warrants auto-revoke; live PR/ticket liveness is the runner's prune |
| Token burn | **aligned** | token-free pre-filter before spawning sub-agents; caps stay with loop-cost |
| Comprehension debt | **partial** | warrant ledger documents guarantees; not a substitute for review |
| Notification fatigue | **marginal** | high-precision triggers; routing/digest is the runner's |
| Parallel collision | **no** | worktree/branch locks — defer entirely |
| Cognitive surrender | **cultural** | explicit claims state intent; human gates are process |

## One-line positioning

Dorian is the **deterministic truth layer for AI coding loops** — it keeps the loop honest
by warranting its load-bearing claims and steering the next iteration when one breaks. It
does not replace loop-engineering; it is the model-free verifier loop-engineering says every
serious loop needs.
