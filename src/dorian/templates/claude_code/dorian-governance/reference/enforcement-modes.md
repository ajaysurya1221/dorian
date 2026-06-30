# Enforcement modes — fail-open vs fail-closed

The `PreToolUse` veto's behavior depends on the policy/effort mode, because the right default
differs when a human is at the keyboard vs when the loop runs unattended.

`strict` = `DORIAN_POLICY=unattended` **or** `DORIAN_EFFORT=godmode`.

| Condition (before a mutating tool runs)        | Attended (cautious/assist) | Strict (unattended/godmode) |
|------------------------------------------------|----------------------------|-----------------------------|
| Malformed tool JSON on stdin                   | allow (exit 0)             | **block (exit 2)**          |
| No decision packet found                       | allow (exit 0)             | **block (exit 2)**          |
| Packet stale (> 15 min) or identity mismatch   | allow (exit 0)             | **block (exit 2)**          |
| Decision is `escalate`, path is sensitive      | **block (exit 2)**         | **block (exit 2)**          |
| Decision is `escalate`, ordinary path          | allow (exit 0)             | **block (exit 2)**          |
| Decision is `continue` / `repair`              | allow (exit 0)             | allow (exit 0)              |

Rationale:

- **Fail closed under strict modes.** With no human watching, a missing/stale/mismatched packet
  must not silently let an escalated loop keep mutating — the safe default is to block and force a
  human in. A leftover packet from a prior run or worktree can never enforce (identity guard).
- **Fail open under attended modes.** A human is present, so a missing packet should never trap the
  agent mid-task; the human is the backstop.
- **Sensitive paths always block on `escalate`**, regardless of mode — the built-in
  `SENSITIVE_GLOBS` jurisdiction (secrets, CI, infra, auth, migrations) is the load-bearing
  defense and is never auto-repaired.

## Freshness window

`FRESH_SECONDS = 900` (15 minutes). The `SubagentStop` hook stamps `created_at_epoch` (host
wall-clock) when it writes the packet; under strict mode the veto rejects an older packet. Tune
the constant in `hooks/dorian_preflight_veto.py` if your turns run longer.

## What is NOT here

The exit-2 mapping, the wall-clock/nonce, and the `hookSpecificOutput` are all **host-hook**
concerns. `dorian gate` and the deterministic core never use exit 2 as a veto, never read a clock,
and never emit Claude-Code-specific output — keeping the verdict path pure and portable.
