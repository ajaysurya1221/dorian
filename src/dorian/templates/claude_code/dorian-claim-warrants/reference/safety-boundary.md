# Safety & trust boundary

## The model drafts. Dorian proves.

This skill (and the optional Stop hook) only **draft** a change note and a
`claims.json`. That is *all* the model decides. The proof step is `dorian verify`,
which runs each claim's **deterministic** checker against the real source — AST
parsing, regex, file/symbol lookup, an actual `pytest` run — with **no LLM, no
model, no judgment call** anywhere in the loop. A warrant is *born verifiable*: if a
load-bearing checker FAILs or ERRORs, the seal is **refused** and nothing is written
(exit 4). **The model cannot make a false claim seal.**

Never tell the user a claim is "verified" unless `dorian verify` actually exited 0
and wrote a `.warrant`. Until then it is a **DRAFT — not verified**.

## Dorian is not a sandbox

`dorian verify` and `dorian revalidate` execute checker programs. `C3` and typed
`C5` only inspect files, but **`C4 pytest:` and `C5 shell:` execute code** (pytest
collection imports the target module and any `conftest.py`). Treat an
agent-emitted `claims.json` exactly as you treat agent-emitted code: **review it
before you run `verify`, and only ever run it in a trusted repo.** Dorian is built
for trusted, internal repositories — **not** public CI taking forked pull requests.
In a semi-trusted context add `--deny-exec` (env `DORIAN_DENY_EXEC=1`) so `C4`/`C5
shell:` ERROR instead of running — fail-closed, but **still not a sandbox**.

## What this is NOT

- Not an LLM judge — no model runs at check time, ever.
- Not a semantic verifier of the whole summary — it checks only the claims someone
  wrote, and cannot catch a lie of omission.
- Not a replacement for tests, SAST, CI, code review, or human judgment.
- Not a generic PR reviewer, dashboard, or SaaS.

## Not "Agent Receipts"

Dorian claim warrants are **not** the Agent Receipts / Obsigna protocol. Agent
Receipts records a cryptographically signed, hash-chained audit trail of *what an
agent did* (its tool calls) — "what did it do, on whose authority, with what
inputs". Dorian answers a different question: *is this specific engineering claim
true now, and will it revoke when later code makes it false?* The word "receipt"
here is an explanatory metaphor, not that protocol. The two are complementary, not
substitutes — see Dorian's `docs/CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md`.

## The optional Stop hook

`.claude/hooks/dorian_claim_warrants_stop.py` is **reminder-only and opt-in**. It is
not enabled by scaffolding; it runs only after you register it under `hooks.Stop` in
your project `settings.json`. It returns a soft `additionalContext` nudge, never a
block, so it cannot loop. It never runs `dorian verify`, never runs tests, never
writes files, and never executes project code — its only side effect is a read-only
`git status` to see whether anything changed.
