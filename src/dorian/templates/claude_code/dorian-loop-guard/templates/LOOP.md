# LOOP.md — loop spec (example)

The durable *design* of the coding loop that maintains this repo. Edit it to fit; the
loop runner and the `/dorian-loop-guard` skill read it. Dorian is the deterministic
verify step — it does not run, schedule, or budget the loop.

## Purpose
<!-- One verifiable goal. e.g. "Keep the public API claims true as the code drifts." -->

## Cadence
<!-- e.g. on pull_request, or a daily schedule via .github/workflows/dorian-loop.yml -->

## Scope (the loop's lane)
- allow: `src/**`, `docs/**`
- denylist (never auto-edit): `infra/**`, `.github/workflows/**`, `**/secrets/**`, `**/*.pem`

## Verification commands
```bash
# before each iteration: deterministic steering signal
dorian loop preflight --since <base> --policy unattended --scope 'src/**' \
  --max-repairs 3 --state-file STATE.json --format json
# after a change: seal new warrants (model drafts, dorian proves)
dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
# your own gates (Dorian complements, never replaces these):
make lint && make test
```

## Steering policy
- `continue` → next planned step, stay in scope.
- `repair` → fix the smallest cause of a broken load-bearing claim, re-check, log it.
- `escalate` → stop autonomous edits, hand off to a human (see STATE.md "waiting on human").

## Escalation rules
Escalate (do not auto-repair) when Dorian preflight says so: a checker ERRORED, the repair
cap was reached, a sensitive/denylisted path is involved, a break is outside scope, or an
`unattended` run has no scope. Deliver escalations to the Human Inbox in STATE.md.

## Safety gates
- No auto-merge except trivial, allowlisted paths.
- Worktree isolation for parallel work (loop runner's job, not Dorian's).
- Kill switch: pause the schedule on repeated escalation or budget overrun.

## Non-goals
Dorian does not judge whole-loop success, replace tests/review, sandbox execution, or
manage cost/worktrees. It verifies specific written claims, token-free, on a trusted repo.
