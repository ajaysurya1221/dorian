# Change note — production-readiness audit + usefulness doc

Adds two durable docs — [`PRODUCTION_READINESS_AUDIT.md`](../PRODUCTION_READINESS_AUDIT.md) (an
evidence-backed readiness review) and [`DORIAN_USEFULNESS.md`](../DORIAN_USEFULNESS.md) (why Dorian
matters, strength-labeled) — and corrects the README's flagship demo, which mis-kinded an existence
claim as `behavior` (now `reference`, so the headline demo is clean under the project's own
`--strength-gate`). No code behavior, warrant schema, checker grammar, exit codes, or security
posture changes.

This note is itself dogfooded: the checkable claims behind it are in
[`production-readiness-audit.claims.json`](production-readiness-audit.claims.json), sealed under
`--strength-gate=fail` — the same truth-axis gate the audit describes. The load-bearing facts are the
two-axis implementation (binding gate = trigger, strength gate = truth) and the invariants the audit
relies on: Python `>=3.11` and a zero-dependency core.
