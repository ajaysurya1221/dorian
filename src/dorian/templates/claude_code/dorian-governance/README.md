# Dorian governance adapter (Claude Code)

Two host hooks that turn Dorian's deterministic loop decision into Claude Code enforcement:

- **`hooks/dorian_loop_preflight.py`** (`SubagentStop`) — after each sub-agent turn, shells the
  pure `dorian gate` (which emits only contract codes `0`/`4` and a JSON decision packet),
  stamps run identity + wall-clock freshness, and writes the packet to the ephemeral
  `.dorian/local/last-decision.json`. It returns the steer as a soft `additionalContext` nudge
  and never blocks at this point.
- **`hooks/dorian_preflight_veto.py`** (`PreToolUse`) — before a mutating tool runs, reads that
  packet and **exits `2` to block** the tool when the standing decision is `escalate`.

The split is deliberate (Dorian's non-negotiables):

- **Dorian core / `dorian gate` only ever emit contract codes `0`/`4`** and a plain JSON packet —
  no `exit 2` veto, no wall-clock, no randomness, no Claude-Code-specific output.
- **The exit-2 tool-block veto, the `hookSpecificOutput`, and the wall-clock/nonce stamping live
  only in these host hooks** — the mapping from a deterministic decision to Claude Code's blocking
  convention is host-side, not in the verifier.

## Wire it up

1. Merge `settings.dorian-governance.example.json` into your `.claude/settings.json`.
2. Before launching the agent, export the loop window + identity:
   - `DORIAN_BASE` — the loop's base git ref (required; without it the hooks stay silent).
   - `DORIAN_POLICY` — `cautious` | `assist` | `unattended` (default `assist`).
   - `DORIAN_EFFORT` — set to `godmode` for the strictest court.
   - `DORIAN_SCOPE` — comma-separated jurisdiction globs (e.g. `src/**,tests/**`).
   - `DORIAN_REPO_ROOT`, `DORIAN_NONCE` — run identity; under strict mode the veto refuses a
     packet whose `repo_root`/`base_ref`/`nonce` don't match, or that is older than 15 minutes.
3. Add `.dorian/local/` to your `.gitignore` — the runtime decision packet is ephemeral and
   must never be committed (it is non-authoritative and is never read back into a verdict).

## Fail-open vs fail-closed

See [`reference/enforcement-modes.md`](reference/enforcement-modes.md). In short: **strict modes
(`unattended` / godmode) fail CLOSED** — a missing, stale, or mismatched packet blocks the tool;
**attended modes fail OPEN** — a human is present, so a missing packet never traps the agent.

## Trust boundary

This is **not a sandbox**. It governs *which decisions block which tools* on a trusted, internal
repo; it does not isolate the filesystem, network, or process. For semi-trusted contexts pair it
with `--deny-exec` / `--checker-source base` and OS-level isolation. This is one concrete Claude
Code adapter — no generic provider abstraction exists until a second adapter does.
