# STATE.md — live loop state (example)

The mutable working memory of the loop. The loop runner / agent updates it every run.
Dorian never writes this file; it only *reads* an attempt count when you pass
`--state-file`. (For the machine-read count, keep a small `STATE.json` alongside this
file — see the bottom.)

## Current objective
<!-- what this iteration is trying to do -->

## Last run
- timestamp: <!-- ISO 8601 -->
- base/ref: <!-- the --since base used -->
- Dorian decision: <!-- continue | repair | escalate -->

## Open loop items (watch list)
<!-- - [ ] item ... -->

## Revoked claims to repair
<!-- from preflight broken_claims[]: claim_id · artifact · bound files · attempts -->

## Waiting on human (escalation queue)
<!-- escalations from Dorian: reason + claim ids + evidence + bound files. Alert if any
     item here is older than 24h. -->

## Recent noise (ignore this cycle)
<!-- non-load-bearing DEGRADED breaks deliberately deferred -->

---

Machine-read attempt count for `dorian loop preflight --state-file STATE.json`:

```json
{ "repair_attempts": 0 }
```
<!-- Keep the JSON above in STATE.json. Increment repair_attempts after each repair
     attempt on the current broken set; reset to 0 once the loop returns to continue.
     Reaching --max-repairs makes preflight escalate (infinite-fix-loop guard). -->
