# Dorian Loop Guard

**The deterministic truth layer for AI coding loops.** Loop Guard turns Dorian's claim
warrants from post-hoc receipts into the loop's *truth memory* and *steering signal*:
before each iteration it re-checks the warrants the change touched and returns a
**CONTINUE / REPAIR / ESCALATE** decision — token-free, no model at check time.

## What it is

A thin classifier on top of `dorian revalidate`. `dorian loop preflight` runs the same
deterministic re-check `revalidate` does, reads each touched warrant's post-fold trust
state, and maps the result to a loop decision packet (JSON / markdown / text). The
verdict is exactly `revalidate`'s — Loop Guard adds no new verification, no model, no
tokens.

## What it is not

- **Not a whole-loop judge.** It verifies only the specific warranted claims a change
  touched — never that "the change is good" or "the loop succeeded". It cannot catch a
  lie of omission.
- **Not a replacement** for tests, SAST, code review, or human judgment — complementary.
- **Not a loop runner.** It does not schedule the loop, manage worktrees, deliver
  notifications, or estimate token cost. Those belong to a loop framework (e.g.
  [loop-engineering](https://github.com/cobusgreyling/loop-engineering)'s loop-init /
  loop-audit / loop-cost). See [LOOP_ENGINEERING_ALIGNMENT.md](LOOP_ENGINEERING_ALIGNMENT.md).
- **Not a sandbox.** `preflight` calls `revalidate`, which *runs* each touched claim's
  checker; `C4 pytest:` / `C5 shell:` execute code. Use it on **trusted, internal repos**.

## Why loops need a deterministic truth layer

The loop-engineering failure catalog's single biggest trap is **weak verification**: the
agent that wrote the code grading its own work, or a verifier that says "looks good"
without running anything (*verifier theater*). The fix is an *independent* verifier — and
the most independent verifier possible is one that runs **no model at all**. A claim
warrant either matches the current code or flips to `REVOKED`, leaving an inspectable
sidecar. Dorian cannot rubber-stamp, cannot be talked past, and costs zero tokens — so it
is the natural deterministic floor under a loop's verify step.

## Preflight → continue / repair / escalate

```bash
dorian loop preflight --since <base> --policy assist --format json
```

The decision is a **pure function** of the revalidate result, the policy, the
repair-attempt count, and the scope/denylist (full table in
[loop-decisions.md](../src/dorian/templates/claude_code/dorian-loop-guard/reference/loop-decisions.md)):

| # | Condition | Decision |
|---|-----------|----------|
| 1 | a checker **ERRORED** (could not run) | **escalate** (`fix_environment`) |
| 2 | a break exists and `repair_attempts >= max_repairs` | **escalate** (infinite-fix cap) |
| 3 | a broken/errored claim is bound to a **sensitive / denylisted** path | **escalate** |
| 4 | a **load-bearing** break is **outside `--scope`** | **escalate** (over-reach) |
| 5 | `unattended` policy with **no `--scope`** and a load-bearing break | **escalate** |
| 6 | a **load-bearing** break, in scope, under the cap | **repair** |
| 7 | only **non-load-bearing** breaks | `cautious`: repair · else continue (warn) |
| 8 | no breaks (TRUSTED / nothing warranted touched) | **continue** |

Policies: **cautious** (repairs even non-load-bearing breaks; cap 1), **assist** (default;
repairs load-bearing, continues past non-load-bearing; cap 3), **unattended** (like assist
but requires `--scope` before repairing a load-bearing break — an L3 loop needs a bounded
lane; cap 3).

**Exit codes.** `preflight` exits **0 on success regardless of the decision** — Dorian
does not stop the loop by default; the decision lives in the output. For a hard CI gate,
opt in with `--fail-on repair` or `--fail-on escalate` (exit 4 at/above that severity) — the
same opt-in-to-block spirit as the claim-warrants Action's `fail_on: revoked`, but here the
default is non-blocking. The shipped Action example uses `--fail-on escalate`.

## Claim warrants as loop memory

After a change, the loop drafts and seals new warrants with **`/dorian-claim-warrants`**
and `dorian verify`. Those `.warrant` sidecars are the loop's **deterministic memory**:
the next iteration's preflight *revalidates* them instead of re-deriving the facts, and
`REVOKE`s the ones a later edit broke — so a stale assumption surfaces as a steering
signal rather than rotting silently in `STATE.md`.

## Example `LOOP.md` / `STATE.md` / run log

`dorian loop install --with-state` writes example
[`LOOP.md`](../src/dorian/templates/claude_code/dorian-loop-guard/templates/LOOP.md) (the
loop's durable spec: purpose, cadence, scope, verification commands, escalation rules),
[`STATE.md`](../src/dorian/templates/claude_code/dorian-loop-guard/templates/STATE.md)
(live working memory + a machine-read `repair_attempts` counter for `--state-file`), and
[`loop-run-log.md`](../src/dorian/templates/claude_code/dorian-loop-guard/templates/loop-run-log.md)
(append-only run history). These follow loop-engineering's conventions; Dorian only
*reads* the attempt count (via `--state-file`) — it never writes loop state.

## Example loop run

```text
$ dorian loop preflight --since main~1 --policy assist --format text
decision: REPAIR  (policy=assist)
  1 load-bearing claim(s) REVOKED, in scope and under the repair cap — repair the
  smallest cause (or update the claim/doc if the change was intentional).
  trust: trusted=0 warranted=0 degraded=0 revoked=1 errored=0
  BROKEN  login-timeout-30s  [load-bearing]  C3: regex_missing
          paths=src/api/config.py  -> repair_code
  next: REPAIR: fix the smallest cause of these broken claim(s): login-timeout-30s …
```

The loop restores the timeout (or updates the claim), re-runs `dorian revalidate --since
main~1` to confirm TRUSTED, logs the attempt, and continues. After the repair cap, the
same break returns `escalate` instead of looping forever.

## Failure modes Dorian helps with

Weak verification, verifier theater, the infinite-fix-loop signal (paired with the cap),
and the escalation *trigger*. It partially helps with over-reach (`--scope`), state rot
(code-anchored warrants auto-revoke), token burn (a cheap deterministic pre-filter before
spawning sub-agents), and comprehension debt (a machine-checked ledger of guarantees).

## Failure modes Dorian does NOT solve

Parallel collision (worktree isolation / locks — defer to the loop runner), notification
*delivery* and digesting, budget/cost estimation, cognitive surrender and comprehension
debt at the cultural level, and live PR/ticket liveness (state rot beyond code-anchored
facts). Dorian provides the signal; the loop runner owns scheduling, delivery, and budget.

## Trusted-repo / not-a-sandbox boundary

`preflight` executes the touched claims' checkers through `revalidate`. `C4 pytest:` and
`C5 shell:` run code with your privileges — **this is not a sandbox**. Use Loop Guard on
trusted, internal repos. For semi-trusted contexts pass `--deny-exec` (refuse the
executable families — fail-closed) and/or `--checker-source base` (never run a PR-added
checker); neither is a sandbox. See [SECURITY_BOUNDARY.md](SECURITY_BOUNDARY.md).

## How to use with Claude Code

```bash
dorian loop install            # scaffolds .claude/skills/dorian-loop-guard/ (/dorian-loop-guard)
dorian loop install --with-state --with-action   # + LOOP.md/STATE.md/run-log + a GH Action example
```

Invoke **`/dorian-loop-guard`** when driving an autonomous loop. The skill tells Claude to
run preflight before each iteration and act on the decision; after a change it hands off to
`/dorian-claim-warrants` to seal new warrants.

## How to use with GitHub Actions

`dorian loop install --with-action` writes an example
[`.github/workflows/dorian-loop.yml`](../src/dorian/templates/claude_code/dorian-loop-guard/templates/dorian-loop.yml)
that runs `dorian loop preflight --fail-on escalate` on each pull request and writes the
markdown packet to the job summary. It blocks only on ESCALATE by default (tighten with
`--fail-on repair`). For public/fork PRs add `--checker-source base --deny-exec`.

## How to combine with loop-engineering tools

Dorian is a drop-in **L2/L3 verifier primitive**: run `dorian loop preflight` as the
deterministic verify step, map its decision onto the loop's commit-vs-escalate gate, and
let the `.warrant` trail complement `loop-run-log.md` as the deterministic-evidence ledger.
Keep scheduling, worktree isolation, cost estimation, and readiness scoring in
loop-engineering's own tools (loop-init / loop-audit / loop-cost) — Dorian does not compete
with them. See [LOOP_ENGINEERING_ALIGNMENT.md](LOOP_ENGINEERING_ALIGNMENT.md).
