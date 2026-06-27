---
name: Dorian claim warrants
description: >-
  Draft and verify Dorian claim warrants for the checkable subset of a coding
  agent's change summary — config values, signatures/defaults, constants, and
  file/symbol references. Use when the user asks to create claim warrants, warrant
  what changed, turn a change summary into checkable claim warrants, or run dorian
  verify on a finished change. The model only drafts; `dorian verify` proves it
  deterministically and token-free. Trusted repos only.
when_to_use: >-
  After finishing a coding change and you want the checkable facts in the summary
  held honest as the code drifts. Triggers: "claim warrants", "warrant this
  change", "dorian verify", "claim warrants for what I changed".
---

# Dorian claim warrants

Invoke with **`/dorian-claim-warrants`** after a coding change. Turn the
**checkable** facts in a coding agent's change summary into deterministic git
`.warrant` receipts that **revoke when later code makes one false** — token-free.

**You only DRAFT. Dorian PROVES.** A claim is **DRAFT — not verified until Dorian
verify passes** (exits 0 and writes a `.warrant`). No model runs at check time.
Dorian is **not a sandbox** and runs in **trusted repo**s only — `C4 pytest:`/`C5
shell:` checkers execute code. See [reference/safety-boundary.md](reference/safety-boundary.md).

## Steps

### 1. Orient
- Find the repo root (`git rev-parse --show-toplevel`).
- Read `git status --short` and `git diff` (and `git diff --staged`) to see what
  *actually* changed. The diff is ground truth.
- Use the agent's final summary if available; **if there is no summary, write a
  short change note from the real diff — never from imagination.**
- Choose a short kebab-case `<slug>` for the change.

### 2. Extract only checkable claims
Include only statements a deterministic checker can falsify:
- config / package-metadata values
- Python signatures / defaults
- Python constants
- path / symbol references
- anchored string / regex facts
- a behavior claim **only** when a real, safe, known-passing `pytest` node exists

Exclude (leave as prose): "cleaner", "better", "faster", "more maintainable",
"refactored", "updated docs", and any security/performance/behavior claim without a
falsifying checker. See [examples/bad-claims.md](examples/bad-claims.md).

### 3. Choose strong checkers
Match the checker to the claim's `kind` — full map in
[reference/checker-selection.md](reference/checker-selection.md). Quick guide:
- config / package value → `config-value:` · signature → `py-signature:` ·
  constant → `py-const:` · existence/reference → `symbol:`/`path:` · anchored value
  → `regex:` (anchor key **and** value) · real behavior → `C4 pytest:`.
- Never back a **behavior** claim with mere `symbol:` existence; never back a
  **quantity** value with a bare existence check. `--strength-gate=fail` refuses both.
See [examples/good-claims.json](examples/good-claims.json) for a worked set.

### 4. Write draft artifacts
Write two files (default paths):
- `docs/changes/<slug>.md` — from [templates/change-note.md](templates/change-note.md):
  human summary · checkable claims included · non-checkable claims **intentionally
  excluded** · the exact verify command · the trust-boundary note.
- `docs/changes/<slug>.claims.json` — valid, minimal; from
  [templates/claims.json](templates/claims.json). Stable kebab-case `id`s;
  `load_bearing: true` only for facts whose breakage should block a merge.

### 5. Verify, or prepare verification
**Review-first (default).** Draft the files, then print the exact command and stop:
```bash
dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
```
Tell the user: **"DRAFT — not verified until Dorian verify passes."** Do not claim
anything is verified.

**Trusted-local (only if the user has explicitly approved running Dorian here).**
Run the command above. Then:
- If it exits 4 because a claim is false, **revise or drop that claim** and say why —
  never fake a checker.
- If it ERRORs because the environment is missing (no `pytest`, etc.), report it as
  fail-closed; do not pretend it passed.
- Preserve `--binding-gate=warn` warnings; do not hide them (weak binding = lower
  coverage, **not** a false claim).
- Say "verified" **only** if `dorian verify` actually exited 0 and wrote a `.warrant`.

### 6. Final response — use this template
```
Artifact written:    docs/changes/<slug>.md (+ .claims.json)
Claims drafted:      <ids + one-line each>
Claims excluded:     <the prose you intentionally did not warrant>
Dorian command run:  <the verify command, or "not run — review-first">
Exit code:           <0 / 4 / 5 / not run>
Warrant created:     <docs/changes/<slug>.md.warrant, or "no — DRAFT only">
Warnings:            <binding/strength diagnostics, verbatim>
Files to commit:     docs/changes/<slug>.md, .claims.json, and the .warrant (once sealed)
Trust boundary:      model drafted; Dorian verifies deterministically; not a sandbox; trusted repo only.
```

## Later: revalidation
On a future PR, `dorian revalidate --since <base>` re-checks only the affected
claims and folds a broken warrant to `REVOKED` (exit 4) — token-free. Commit the
`.warrant` alongside the change so the GitHub Action can re-check it.

## Hard rules
- The model drafts; **Dorian verifies**. Never seal by asserting — only `dorian
  verify` seals.
- Never imply Dorian verified the *whole* summary, sandboxed anything, or proved
  truth by itself.
- Keep the two axes apart: binding = *when* re-checked; strength = *whether*
  falsifiable. A warning is low confidence, **not** a false claim.
- These are **not** "Agent Receipts" (that protocol audits agent *actions*); see
  [reference/safety-boundary.md](reference/safety-boundary.md).
