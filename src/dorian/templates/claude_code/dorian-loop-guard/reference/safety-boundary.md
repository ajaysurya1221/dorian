# Loop guard — safety boundary

Dorian Loop Guard is a **steering** layer, not a judge and not a sandbox. Keep these
distinctions exactly:

## What Dorian decides

- Whether the **specific warranted claims** a change touched still hold, by re-running
  their deterministic checkers (`dorian revalidate`). No model runs at check time.
- A CONTINUE / REPAIR / ESCALATE signal computed deterministically from that result plus
  your policy, repair cap, and scope.

## What Dorian never decides

- Whether the **whole loop** succeeded. Dorian verifies only claims someone wrote; it
  cannot catch a lie of omission, and a clean preflight is **not** "the change is good".
- Whether the code is *correct*, *secure*, or *well-designed*. Those need tests, SAST,
  review, and human judgment — Dorian is complementary, never a replacement.
- It does not run, schedule, or budget the loop, and it does not deliver notifications or
  manage worktrees. Pair it with your loop runner.

## Verdict vocabulary (do not collapse)

- **REVOKED** — a load-bearing claim broke. A *steering signal* (repair or escalate), not
  a moral failure and not a reason to halt by default.
- **DEGRADED** — a non-load-bearing claim broke. Lower priority; policy decides repair vs.
  continue.
- **ERRORED** — a checker could not run. **Fail-closed evidence, not a false claim** —
  escalate and fix the environment; never weaken the checker to make it pass.
- **weak binding / weak strength** — low coverage / low confidence, **not** a false claim.
  Two separate axes: binding = *when* a claim re-checks; strength = *whether* the checker
  can falsify it. Never hide a binding/strength warning.

## Trust boundary

`dorian loop preflight` calls `revalidate`, which **runs** each touched claim's checker.
`C4 pytest:` and `C5 shell:` execute code. **This is not a sandbox** — allowed checkers
run with your privileges. Use Loop Guard on **trusted, internal repos**. For semi-trusted
contexts, pass `--deny-exec` (refuse the executable families — fail-closed) and/or
`--checker-source base` (never run a PR-added checker); neither is a sandbox. See the main
[docs/SECURITY_BOUNDARY.md](https://github.com/ajaysurya1221/dorian/blob/main/docs/SECURITY_BOUNDARY.md).

## The handshake

The loop's model **plans, repairs, and summarizes**. Dorian **proves** the checkable
claims deterministically. Keep that line: never report a claim "verified" unless
`dorian verify`/`dorian revalidate` actually said so.
