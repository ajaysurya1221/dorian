# Extraction gate results — calibration failed twice; approach rejected (2026-06-13)

This is the results record for the pre-registered planted-truth extraction
gate ([`EXTRACT_GATE.md`](EXTRACT_GATE.md), pushed publicly before any
battery run). The headline is a **negative result about the validation
approach itself**: the synthetic battery failed its instrument-calibration
precondition twice, and per the pre-registered rule — *"a second calibration
failure after generator revision triggers the rejection of this validation
approach"* — the planted-truth route to promoting `--extract` is closed.
**`--extract` status is unchanged: experimental, draft-only.** The promotion
and rejection gates for the extractor were never validly evaluated.

## What was run

15 generated documents (3 tiers ≈40/120/240 lines × 5 seeds), both modes,
3 single-extraction draws each (`claude-sonnet-4-6`, temperature 0, cache
disabled) — the calibration phase only. The consensus gate phase was never
reached, exactly as the protocol prescribes when calibration fails.

## Attempt 1 — v1 generator (single-clause claim templates)

| condition | required | measured | result |
|---|---|---|---|
| (a) restate pooled churn > anchor pooled | yes | 0.098 > 0.000 | pass |
| (b) restate churn rises 40 → 240 lines | yes | 0.092 → 0.071 | **fail** |
| (c) restate churn ≥ 0.20 at 240 lines | yes | 0.071 | **fail** |

Diagnosis: single-clause template claims ("The default request timeout is
30 seconds.") are short enough for the restate model to reword
*consistently*, so the battery never stressed the per-run decomposition
choices real documents force. One generator revision was permitted and
taken: compound multi-clause claims with qualifiers and 2–3 checkable
tokens per sentence.

## Attempt 2 — v2 generator (compound claim templates)

| condition | required | measured | result |
|---|---|---|---|
| (a) restate pooled churn > anchor pooled | yes | 0.266 > 0.001 | pass |
| (b) restate churn rises 40 → 240 lines | yes | 0.370 → 0.141 | **fail** |
| (c) restate churn ≥ 0.20 at 240 lines | yes | 0.141 (0.177 corrected¹) | **fail** |

¹ One 240-line document's restate runs all truncated at the output-token
limit (43 compound claims overflow a single restate call — itself a real
restate-mode failure worth recording). The harness scores empty-vs-empty
draws as churn 0.0, which flatters the failing mode; this is a measurement
limitation, now documented. Excluding that document raises the tier mean to
0.177 — conditions (b) and (c) **still fail**, so the artifact does not
change the verdict.

## The central finding: the synthetic-to-real gap

Measured twice, in both directions of the battery design:

| | planted docs (40–240 lines) | real docs (34–152 lines, v0.5.0) |
|---|---|---|
| anchor single-extraction churn | ≈ 0.000–0.004, recall 0.994 | 0.04–0.37, growing with length |
| restate churn vs length | flat or **falling** | **rising** (0.32 → 0.78) |

Generated documents — even with compound, qualifier-laden claims — are
systematically easier than real prose: template regularity and a clean
claim/filler boundary remove exactly the ambiguity that causes selection
jitter on real documents. A promotion decision made on this battery would
have been **optimistically wrong**, which is precisely the failure mode the
calibration precondition exists to catch. The mechanism worked; the
instrument did not.

What the exercise did validly establish, within its scope: the
restate-vs-anchor discrimination reproduced both times (restate churns an
order of magnitude more on every battery), the harness/transform/consensus
machinery is exercised end-to-end by 16 offline tests, and restate mode
cannot handle claim-dense long documents in a single call.

## Consequences

1. **`--extract` remains experimental and draft-only.** No promotion, no
   demotion: the extractor's gates were never validly evaluated.
2. **The planted-truth battery is retired as a promotion instrument.** The
   generator and harness remain in `bench/` as test infrastructure (the
   offline tests pin their determinism), but no future promotion claim may
   cite planted-battery numbers.
3. **The honest label-free path forward** (named, not built; requires its
   own pre-registration before any run): metamorphic relations applied to
   **real** documents, which need no planted truth and no human labels —
   (i) extraction invariance under filler-insert and section-reorder on
   real documents (compare extractions before/after a meaning-preserving
   edit; no ground truth needed), and (ii) anchor-targeted deletion (delete
   the exact line a claim anchored to, re-extract, the claim must vanish —
   a fabrication check anchored by the extractor's own output). Both
   operate at real-document difficulty by construction, eliminating the
   transfer problem that killed this gate.

No number in this document is human-verified, and none may be quoted as
real-history extraction performance; raw per-document calibration artifacts
are local-only, with aggregates reproducible from `bench/plant.py` seeds
(1–5 per tier) and the commands in `EXTRACT_GATE.md`.
