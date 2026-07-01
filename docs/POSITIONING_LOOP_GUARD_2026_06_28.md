# Positioning — Dorian Loop Guard (2026-06-28)

A focused reframe that reconnects Dorian to the original goal: *people give an AI coding
agent a task, go to bed, and want useful results in the morning — Dorian should not stop
the loop unnecessarily; it should keep the loop on track when something goes off track.*

## The drift, named

v1.3.0 shipped **claim warrants for Claude Code** — the right primitive, but framed as
*post-hoc receipts* ("hold the agent to what it said it did"). That framing answers
"who audits the summary?" but not the deeper goal: **steering a running loop**. Claim
warrants were always capable of being the loop's truth memory; they were just pointed
backward. Loop Guard points them forward.

Verdict: **DRIFTED BUT RECOVERABLE** — recovered by a thin deterministic steering layer
(`dorian loop preflight`) on top of the existing `revalidate` engine. No new verification,
no model, no new trust semantics.

## Tagline candidates (in use)

- **"The deterministic truth layer for AI coding loops."**
- "Keep your coding-agent loop on track when its assumptions drift."
- "Claim warrants that steer the next agent iteration."

## The one-paragraph pitch

You hand an AI coding agent a task and walk away. Loop Guard is the deterministic,
token-free verify step the loop runs before each iteration: it re-checks the claim warrants
the change touched and returns **CONTINUE** (claims still hold), **REPAIR** (a load-bearing
claim broke — fix the smallest cause or update the claim), or **ESCALATE** (a checker
errored, a sensitive path is involved, the repair cap was hit, or the break is out of
scope — hand off to a human). No model runs at check time, so the verifier can't be talked
past, can't rubber-stamp, and costs nothing per check. Dorian doesn't judge whether the
loop *succeeded* — it keeps the loop *honest about the specific facts it warranted*, and it
doesn't stop the loop by default.

## What changed vs the receipts framing

| Receipts framing (1.3.0) | Loop Guard framing (1.4.0) |
|---|---|
| "Warrant what the agent said it did." | "Steer the next iteration from what still holds." |
| Output: a sealed `.warrant` (a receipt). | Output: a CONTINUE/REPAIR/ESCALATE decision packet. |
| Used after a change, for audit. | Used *before each iteration*, for steering; warrants are loop memory. |
| Value: catch a silently-false claim later. | Value: keep an unattended loop on track without stopping it unnecessarily. |

Same mechanism (deterministic warrants + revalidate), same boundaries (not a sandbox, not
an LLM judge, token-free, trusted repos), reconnected to the autonomous-loop goal.

## Honesty guards (unchanged)

REVOKED is a steering signal, not a moral/whole-loop failure. ERRORED is fail-closed
evidence, not a false claim. Weak binding/strength is low confidence, not falsity. Trigger
and truth axes stay separate. Dorian verifies only specific written claims — never
whole-loop success — and complements, never replaces, tests / review / human judgment.
