# The Planted-Truth Extraction Gate (pre-registered)

> **Status (2026-06-13):** instrument calibration failed twice; per the rule
> below, the validation approach was rejected before the gate phase ran.
> Results and consequences: [`EXTRACT_GATE_RESULTS.md`](EXTRACT_GATE_RESULTS.md).
> The thresholds in this document were not altered after pre-registration.

This document pre-registers the validation design and the exact decision
thresholds for promoting or rejecting `--extract`, **before** the gate
battery is run. It is committed and pushed ahead of any results so the
thresholds cannot move after the data arrives. Results will be published
separately and must reference this document.

## Why this gate exists

The validation ladder's Level 1 requires owner ground-truth labels for the
*warrant-value* question (real-history staleness). The `--extract`
promotion decision is narrower — stability, selection correctness, and
non-fabrication of a *draft generator* — and those three properties are
checkable without any human labels:

- **Planted truth:** documents are generated *from* a known claim
  inventory, so which lines are checkable claims is ground truth by
  construction, not by judgment.
- **Metamorphic relations:** meaning-preserving edits (filler insertion,
  section reorder) must not change what is extracted; deleting a claim's
  source line must remove exactly that claim. Violations are mechanical
  failures, not opinions.
- **Selection-vs-boundary decomposition:** churn is measured on
  *covered-claim-line sets* (boundary-insensitive) separately from claim
  text, directly distinguishing genuine selection disagreement from
  off-by-a-line boundary jitter — the split the v0.5.0 battery showed
  matters.

An LLM appears only as the system under test. Every verdict input is a
deterministic computation over generated artifacts.

## The system under test

Anchor-first extraction (v0.4.0) plus two deterministic additions:

1. **Boundary snapping** (stage 2): span edges are trimmed of blank lines,
   headings, horizontal rules, and code-fence markers before ids/text are
   derived.
2. **Consensus-of-k voting** (`k = 3`): k independent span selections; a
   document line is selected iff covered by a strict majority of runs;
   adjacent consensus lines remain one claim only if a majority of runs
   spanned them together; kind/load_bearing by majority vote with
   deterministic tie-breaks (lexicographic kind; load_bearing ties go to
   false). The model still never authors claim text.

## The battery

15 generated documents: 3 length tiers (≈40, ≈120, ≈240 lines — bracketing
the measured failure boundary of v0.5.0) × 5 seeds, built by
`bench/plant.py` from claim templates (every claim line carries a digit,
path, or version token) and distractor templates (mechanically verified to
carry none). ~30% of content lines are planted claims. Per document:
3 independent consensus draws, plus one draw on each of 3 transforms
(filler-insert, section-reorder, claim-delete) from `bench/metamorph.py`.
Model `claude-sonnet-4-6`, temperature 0, cache disabled.

## Instrument calibration (validity precondition)

The battery is a valid instrument only if single-draw measurements on it
reproduce the failure signature already measured on real documents
(v0.3.0/v0.5.0):

- (a) restate-mode pooled exact churn > anchor-mode pooled exact churn;
- (b) restate churn at the 240-line tier > restate churn at the 40-line
  tier;
- (c) restate exact churn ≥ 0.20 at the 240-line tier (the battery is hard
  enough to fail the old mode where real documents did).

If calibration fails, the verdict is **insufficient evidence** regardless
of gate metrics; a second calibration failure after generator revision
triggers the rejection of this validation approach (not silently another
generator tweak).

## Metrics

- **Selection recall** — fraction of planted claim lines covered by at
  least one selected span (per draw, averaged).
- **Selection precision** — fraction of selected spans covering at least
  one planted claim line.
- **Selection churn** — mean Jaccard distance between covered-claim-line
  sets across the 3 consensus draws (boundary-insensitive).
- **Text churn** — the existing normalized-claim-text exact churn across
  draws (post-snapping).
- **Invariance** — of planted claims extracted from the original document,
  the fraction still extracted after filler-insert and section-reorder
  (normalized text match).
- **Fabrication** — deleted planted claims whose text is still extracted
  after the claim-delete transform.

## Pre-registered decision gates

**Promotion gate** (all must hold):
- selection recall ≥ 0.80 pooled AND ≥ 0.70 on the 240-line tier;
- selection precision ≥ 0.75 pooled;
- selection churn < 0.10 mean on every tier;
- text churn < 0.20 on every tier;
- invariance ≥ 0.90 pooled across filler-insert and section-reorder;
- fabrication count = 0.

Outcome: `--extract-mode anchor` with consensus is promoted from
"experimental" to "supported draft generator", with the published wording
stating exactly what was validated (planted-truth + metamorphic + stability)
and what was not (real-history warrant value; claim importance).

**Rejection gate** (any one triggers):
- selection recall < 0.60 pooled;
- selection churn ≥ 0.20 on any tier (consensus failed to stabilize
  selection);
- fabrication count > 0 (a validity tool that invents claims is
  disqualified, full stop);
- calibration fails twice.

Outcome: the anchor/consensus architecture is recorded as failed in
`NEXT_ALGORITHMIC_BETS.md`; `--extract` is demoted from "experimental" to
"not recommended; manual claims only."

**Insufficient-evidence gate** (otherwise):
- any result between the bands, or a single calibration failure.

Outcome: no promotion, no demotion; the specific shortfall is published and
becomes the next measured target. Thresholds do not move post hoc; if a
threshold is judged wrong, that judgment and its rationale are published
and a v2 gate is pre-registered before any re-run.

## What this gate cannot prove

Synthetic documents are not a distributional guarantee for real documents
(calibration detects "too easy", it cannot prove transfer); extraction
*quality of judgment* (which claims are load-bearing) remains a human
review step at seal time by design; and the end-to-end warrant-value claim
on real history remains exactly as caveated in the README — owner-checked,
model-adjudicated, private raw data. No result from this gate may be
quoted as "human-verified" or as real-history performance.
