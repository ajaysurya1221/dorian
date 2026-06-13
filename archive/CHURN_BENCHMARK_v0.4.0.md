# Anchor-first extraction churn — v0.4.0 (vs the v0.3.0 restate baseline)

v0.4.0 implements the anchor-first extraction prototype
(`--extract-mode anchor`, bet 5 of
[`NEXT_ALGORITHMIC_BETS.md`](../docs/NEXT_ALGORITHMIC_BETS.md)): the model only
*selects* 1-based line spans; claim text, anchor, and id are derived from the
artifact deterministically (`cL<start>-<end>`). The model never authors
identity-bearing text, so claim wording cannot churn — only span selection
can. This benchmark measures whether that kills the instability documented in
[`CHURN_BENCHMARK_v0.3.0.md`](CHURN_BENCHMARK_v0.3.0.md).

## Method

Identical protocol to the v0.3.0 baseline: 7 isolated benchmark runs, each
running `dorian bench churn` exactly once (3 independent extraction runs,
`claude-sonnet-4-6`, temperature 0, cache disabled) on its own byte-identical
copy of the same sanitized public demo doc (sha256
`213409f36b91615cab028e460143f2ffa3a3c81e44d45565f5f3b85d5b200a6a`), with
`--mode anchor` as the only difference. Every reported number was recomputed
from the raw `churn.json` artifacts; 7/7 runs valid, none excluded.

## Results

| run | exact churn | claims/run | identical run pairs | gate (< 0.20) |
|---|---:|---|---|---|
| 1 | 0.0000 | 9, 9, 9 | 3/3 | PASS |
| 2 | 0.0000 | 9, 9, 9 | 3/3 | PASS |
| 3 | 0.0667 | 10, 9, 9 | 1/3 | PASS |
| 4 | 0.0667 | 10, 10, 9 | 1/3 | PASS |
| 5 | 0.0000 | 9, 9, 9 | 3/3 | PASS |
| 6 | 0.0667 | 10, 9, 9 | 1/3 | PASS |
| 7 | 0.0000 | 9, 9, 9 | 3/3 | PASS |

Side by side (same doc, same model, same protocol, n=7 invocations each):

| metric | restate (v0.3.0) | anchor (v0.4.0) |
|---|---:|---:|
| exact churn mean | 0.1866 (SEM 0.0317) | **0.0286** (SEM 0.0135) |
| exact churn median | 0.2072 | **0.0000** |
| range | 0.0741–0.2899 | 0.0000–0.0667 |
| advisory-gate pass rate | 3/7 | **7/7** |
| identical run pairs (by normalized claim text) | 3/21 | **15/21** |
| invocations with all 3 runs identical | 0/7 | **4/7** |
| claims per run | 17–18 | 9–10 |

## Reading the numbers

- **The wording-churn failure mode is gone.** Anchor mode's exact churn mean
  is 6.5× lower than restate's, its median is zero, and its worst invocation
  (0.067) churns less than restate's best (0.074). The gate verdict, which
  flipped between PASS and FAIL across restate invocations, is stable: 7/7
  PASS.
- **Residual churn is one borderline span.** Every nonzero invocation is
  exactly one extra span appearing in some runs (10 vs 9). Span *selection*
  jitter — the only degree of freedom the model retains — is now the entire
  churn budget.
- **Acceptance vs bet 5's criteria:** "churn below the 0.20 gate" — met,
  7/7. "3 re-runs produce identical anchor sets and claim ids" — met in 4 of
  7 invocations (15 of 21 run pairs); not yet unconditional.
- **The honest trade-off: granularity.** Anchor claims are line-grained
  (~9/doc vs ~17 restated sub-claims): a line stating two facts stays one
  claim. Restate decomposes finer but cannot hold its wording still. Both
  modes remain drafts for review.
- **Scope of evidence:** one short, structured public document; selection
  stability on longer, messier documents is unmeasured. `--extract` stays
  **experimental and draft-only** in both modes; anchor mode is the
  documented path toward lifting that, not the lifting itself.

Raw per-run outputs (`dorian-churn-v1` schema, now with a `mode` field)
contain doc basenames, counts, and distances only — no document content and
no private material.
