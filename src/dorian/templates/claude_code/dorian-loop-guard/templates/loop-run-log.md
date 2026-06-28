# loop-run-log.md — append-only run history (example)

One entry per loop run, newest last. Separate from STATE.md so you can debug the loop's
decisions over time. Dorian contributes the deterministic `dorian_decision` and the
broken/revoked claim ids; the loop runner records the rest.

```json
{"run_id": "2026-06-28T02:00:00Z", "base": "main~1", "dorian_decision": "continue", "revoked_claims": [], "actions_taken": "ran next planned step", "tests": "lint+test green", "next": "continue", "escalations": 0}
{"run_id": "2026-06-28T03:00:00Z", "base": "main~1", "dorian_decision": "repair", "revoked_claims": ["login-timeout-30s"], "actions_taken": "restored LOGIN_TIMEOUT=30 in src/config.py; revalidate -> TRUSTED", "tests": "lint+test green", "next": "continue", "escalations": 0}
{"run_id": "2026-06-28T04:00:00Z", "base": "main~1", "dorian_decision": "escalate", "revoked_claims": ["db-migration-applied"], "actions_taken": "stopped; migrations/ is a sensitive path", "tests": "not run", "next": "waiting on human", "escalations": 1}
```

Human-readable one-liners (optional, mirror the JSON):

- `2026-06-28T02:00Z` — CONTINUE — no warranted claims affected — next: continue.
- `2026-06-28T03:00Z` — REPAIR — `login-timeout-30s` REVOKED → restored timeout → TRUSTED.
- `2026-06-28T04:00Z` — ESCALATE — `db-migration-applied` on a sensitive path → human.
