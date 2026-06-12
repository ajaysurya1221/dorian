# Extraction-churn benchmark — v0.3.0 (multi-run, blinded inputs)

Seven isolated benchmark agents independently ran `dorian bench churn` on the
committed public demo document, and their verified results were aggregated.
This measures how stable LLM claim extraction is across separate benchmark
invocations — the property that currently keeps `--extract` experimental.

## Method

- **Input:** a sanitized copy of `examples/demo-repo/docs/design.md` (the
  committed fictional public demo doc). Before any run, the claim set was
  sanitized to remove any prior verdict/status tags (`owner-checked`) and
  verified to contain none; each agent received its own byte-identical copy.
  Sanitized claim-set sha256:
  `213409f36b91615cab028e460143f2ffa3a3c81e44d45565f5f3b85d5b200a6a`.
- **Runner isolation:** 7 agents in fresh, isolated contexts; no shared
  state, no knowledge of each other or of the aggregation. Each ran the
  benchmark command exactly once.
- **Per invocation:** 3 independent extraction runs (`claude-sonnet-4-6`,
  temperature 0, forced tool choice, cache fully disabled — every run is a
  fresh model call), pairwise normalized-claim-text Jaccard distances,
  advisory gate `exact_mean < 0.20`. 21 fresh extraction runs total.
- **Validation:** every reported metric was independently recomputed from
  the raw `churn.json` distance arrays; all 7 runs verified, none excluded,
  no reruns needed. All runs shared the same extraction prompt hash.

## Results

| agent | exact churn | fuzzy churn | claims/run | gate (< 0.20) |
|---|---:|---:|---|---|
| 1 | 0.2072 | 0.0000 | 17, 17, 17 | FAIL |
| 2 | 0.2826 | 0.0370 | 18, 18, 17 | FAIL |
| 3 | 0.2899 | 0.0370 | 17, 17, 18 | FAIL |
| 4 | 0.2072 | 0.0000 | 17, 17, 17 | FAIL |
| 5 | 0.1053 | 0.0370 | 18, 18, 17 | PASS |
| 6 | 0.1404 | 0.0000 | 17, 17, 17 | PASS |
| 7 | 0.0741 | 0.0000 | 17, 17, 17 | PASS |

Aggregates over the 7 valid runs (no outliers excluded):

| metric | n | mean | median | min | max | std | SEM |
|---|---|---:|---:|---:|---:|---:|---:|
| exact churn mean | 7 | 0.1866 | 0.2072 | 0.0741 | 0.2899 | 0.0838 | 0.0317 |
| fuzzy churn mean (thr 0.75) | 7 | 0.0159 | 0.0000 | 0.0000 | 0.0370 | 0.0198 | 0.0075 |
| mean claims per run | 7 | 17.24 | 17.00 | 17.00 | 17.67 | 0.32 | 0.12 |
| advisory-gate pass rate | 7 | 3/7 (0.43) | — | — | — | — | — |

## Reading the numbers

- **The gate verdict is unstable.** The exact-churn estimate from any single
  invocation ranges 0.07–0.29 on the same document at temperature 0; only
  3 of 7 invocations clear the 0.20 gate. A single churn run is a noisy
  measurement — and an extractor whose stability gate flips between PASS
  and FAIL across identical invocations is not a stable warrant input.
  This is direct, quantitative support for keeping `--extract`
  **experimental and draft-only**.
- **The churn is mostly wording, not selection, on this document.** Fuzzy
  churn (which forgives rephrasing) is near zero and claim counts barely
  move (17–18); the model re-finds essentially the same claims but words
  them differently run to run. Exact-match identity of claim text is what
  fails.
- **Relation to earlier measurements:** the v0.0 compliant churn record in
  [`KILL_REPORT_v0.0.md`](KILL_REPORT_v0.0.md) measured exact 0.49 / fuzzy
  0.21 on a real (private, longer) document — substantially worse than this
  short structured demo doc, and the basis for the experimental status.
  This benchmark adds the run-to-run variance picture; it does not replace
  that result, and it does not change the experimental status.

Raw per-agent outputs (`churn.json`, `dorian-churn-v1` schema) contain doc
basenames, counts, and distances only — no document content and no private
material.
