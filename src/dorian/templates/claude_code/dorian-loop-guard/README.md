# Dorian loop guard — bundle

This directory is a project-local Claude Code **skill** that wires Dorian into an
autonomous coding loop as the deterministic, token-free **truth + steering layer**. It
was scaffolded by `dorian loop install`.

## What it is

- `SKILL.md` — the skill, invoked as **`/dorian-loop-guard`**. Tells Claude to run
  `dorian loop preflight` before each iteration and act on CONTINUE / REPAIR / ESCALATE.
- `reference/loop-decisions.md` — the full decision table, the three policies, and the
  loop-engineering failure modes Dorian does / does not help with.
- `reference/safety-boundary.md` — what Dorian steers vs. what it never decides; the
  not-a-sandbox / not-a-judge / token-free boundary.
- `templates/LOOP.md`, `templates/STATE.md`, `templates/loop-run-log.md` — example loop
  state files. Copy them to the repo root (or re-run `dorian loop install --with-state`).
- `templates/dorian-loop.yml` — a GitHub Actions example that runs preflight on each
  pull request (fails only on ESCALATE by default).

## The one move

```bash
# before each loop iteration
dorian loop preflight --since <base> --policy assist --format json
# -> {"decision": "continue|repair|escalate", "loop_instruction": "...", ...}
```

- `continue` → do the next planned step (stay in scope).
- `repair` → fix the smallest cause of the broken load-bearing claim(s), re-check, log it.
- `escalate` → stop autonomous edits; hand off to a human with the evidence.

After a change, draft + seal new warrants with **`/dorian-claim-warrants`** and
`dorian verify`; commit the `.warrant`. Those warrants are the loop's memory — the next
preflight revalidates them.

## Boundary

Dorian steers; it does not judge whole-loop success and runs **no model at check time**.
`REVOKED` is a steering signal, `ERRORED` is fail-closed evidence — neither is a verdict
on the loop. Not a sandbox; trusted repos only. Dorian does not schedule the loop, manage
worktrees, deliver notifications, or estimate cost — pair it with your loop runner.
