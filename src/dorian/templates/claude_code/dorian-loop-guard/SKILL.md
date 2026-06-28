---
name: Dorian loop guard
description: >-
  Use Dorian as the deterministic, token-free truth layer that steers an autonomous
  coding loop. Before each iteration, run `dorian loop preflight` to revalidate the
  claim warrants the change touched and get a CONTINUE / REPAIR / ESCALATE decision;
  act on it. Use when running an unattended or long-running coding loop, when the user
  asks to keep a loop on track, steer the next iteration, or wire Dorian into a loop.
  Dorian steers; it does not judge whole-loop success and runs no model at check time.
  Trusted repos only.
when_to_use: >-
  When driving a multi-iteration or unattended coding loop and you want a deterministic
  signal for whether to continue, repair, or hand off to a human. Triggers: "loop
  guard", "keep the loop on track", "dorian loop preflight", "steer the next iteration",
  "should the loop continue or escalate".
---

# Dorian loop guard

Invoke with **`/dorian-loop-guard`** when you are driving an autonomous coding loop.
Dorian is the **deterministic truth layer underneath the loop's verifier step**: it
re-checks the specific claim warrants a change touched and turns the result into a
**CONTINUE / REPAIR / ESCALATE** steering signal — token-free, no model at check time.

**Dorian steers; it does not grade the whole loop.** A `REVOKED` claim is a steering
signal, not a moral failure. An `ERRORED` checker is fail-closed evidence, not a false
claim. Dorian verifies only the specific claims someone wrote — never whole-loop
success. It is **not a sandbox** and runs in **trusted repos** only (`C4 pytest:` / `C5
shell:` checkers execute code through `revalidate`). See
[reference/safety-boundary.md](reference/safety-boundary.md).

Dorian does **not** schedule the loop, manage worktrees, deliver notifications, or
estimate token cost — those belong to your loop runner (e.g. loop-engineering's
loop-init / loop-audit / loop-cost). Dorian plugs in at the verify step.

## The loop, with Dorian in it

### 1. Before each iteration — preflight
Run preflight against the loop's base ref and read the decision:
```bash
dorian loop preflight --since <base> --policy <cautious|assist|unattended> --format json
```
Useful flags: `--scope 'src/**'` (bound the loop's lane — required by `unattended`),
`--max-repairs N` and `--repair-attempts N` (infinite-fix-loop guard), `--state-file
STATE.md.json` (read the prior attempt count), `--deny-path 'infra/**'` (extra sensitive
paths). The packet's `decision`, `reason`, `broken_claims[]`, and `loop_instruction`
tell you what to do.

### 2. If decision is `continue`
- No broken **load-bearing** claim for the changed paths. Proceed with the next planned
  step. Stay inside `--scope`; do not touch out-of-scope or denylisted paths.

### 3. If decision is `repair`
- Read `broken_claims[]`. For each, repair the **smallest cause** in the bound files
  (`paths`), or — if the change was intentional — update the claim/doc instead of the
  code (`suggested_next_step` is a hint, not a verdict).
- Re-run the exact checker or `dorian revalidate --since <base>` to confirm the fix.
- Record the attempt and outcome in `STATE.md` / the run log; increment the repair
  count. **Do not exceed `--max-repairs`** — after the cap, preflight returns `escalate`.

### 4. If decision is `escalate`
- **Stop autonomous edits.** Produce a human handoff from `human_escalation` +
  `broken_claims[]`: the broken claim ids, the evidence, the bound files, and the reason.
- Write it to `STATE.md` under "waiting on human"; do not keep retrying. Escalation
  happens for `ERRORED` checkers, the repair cap, sensitive/denylisted paths, over-reach
  (a break outside `--scope`), or an `unattended` loop with no scope configured.

### 5. After any successful code/docs change — seal new warrants
- Use **`/dorian-claim-warrants`** to draft the change note + `claims.json` for the new
  load-bearing facts, then prove them:
  ```bash
  dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json \
    --strength-gate=fail --binding-gate=warn
  ```
- Commit the sealed `.warrant` alongside the change. Those warrants become the loop's
  **deterministic memory**: the next iteration's preflight revalidates them instead of
  re-deriving the facts, and REVOKEs the ones a later edit breaks.

## Render a next-iteration prompt
To hand the decision to the next agent step as a compact instruction:
```bash
dorian loop prompt --since <base> --policy assist
```

## Policies (pick per autonomy level)
- `cautious` — repair even non-load-bearing breaks; cap 1. For closely-watched loops.
- `assist` (default) — repair load-bearing breaks; continue past non-load-bearing with a
  warning; cap 3.
- `unattended` — like assist, but **requires `--scope`** before repairing a load-bearing
  break (an L3 unattended loop needs a bounded lane); cap 3.

See [reference/loop-decisions.md](reference/loop-decisions.md) for the full decision
table and the failure modes Dorian does / does not address.

## Hard rules
- Dorian **steers**, it does not judge the whole loop. Never report "the loop is
  correct" or "the change is verified" — only that the **named warranted claims** hold
  or broke.
- `REVOKED` ≠ failure-to-stop. It is a signal to repair or escalate, not a reason to
  halt the loop by default (preflight exits 0 unless you set `--fail-on`).
- `ERRORED` is fail-closed evidence (a checker could not run), **not** a false claim —
  escalate it, do not "fix" it by weakening the checker.
- Keep the two axes apart: binding = *when* a claim re-checks; strength = *whether* the
  checker can falsify it. A weak-binding/strength warning is low confidence, **not** a
  false claim — never hide it.
- No model runs at check time. Dorian is not an LLM judge and not a sandbox; trusted
  repos only.
