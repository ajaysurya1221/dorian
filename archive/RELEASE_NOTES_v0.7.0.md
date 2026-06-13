# dorian v0.7.0 — controlled-mutation benchmark

v0.7.0 makes the project's public benchmark evidence numeric and reproducible.
It adds a known-truth controlled-mutation benchmark, retires the earlier
benchmark-evidence narrative that relied on a private review process, and lets
the numbers speak for themselves.

## What's new

- **`docs/BENCHMARK_v0.6.0.md` + `dorian bench mutation`** — a controlled-mutation
  benchmark on a single invented, synthetic fixture. Each mutation's stale /
  not-stale label is a **mechanical consequence of the edit** (frozen before
  measurement), so the result needs no review judgment of any kind. It compares
  dorian's claim-level revalidation against two file-change-watcher baselines (a
  naive whole-file watcher and a stronger line-aware diff-hunk watcher) and
  reports the full confusion matrix, precision/recall with in-fixture bootstrap
  CIs, false-positive reduction (with raw counts), and dorian's own false
  positives and false negatives. Output is deterministic (byte-identical across
  runs); the summary carries only aggregate numbers, the fixture's public file
  names, and mutation ids.
- **Evidence cleanup.** The earlier private review pipeline and its public
  summary generator are removed; the README's benchmark section is now numbers
  only. Superseded v0.0 records are moved to `archive/` and are no longer cited
  as current evidence.

## Benchmark numbers (measured on the committed fixture, 41 pairs, 0 errored)

| detector | TP | FP | FN | TN | precision | recall |
| --- | --- | --- | --- | --- | --- | --- |
| naive file-watcher | 19 | 20 | 0 | 2 | 0.49 | 1.00 |
| line-aware watcher | 19 | 15 | 0 | 7 | 0.56 | 1.00 |
| dorian | 16 | 5 | 3 | 17 | 0.76 | 0.84 |

False-positive reduction: 4.0x vs the naive watcher (20 vs 5), 3.0x vs the
line-aware watcher (15 vs 5). dorian trades some recall (three substring-checker
misses) for substantially higher precision; the gap holds against the line-aware
baseline, not only the naive one.

## Caveats — read before relying on it

- These numbers describe **one synthetic fixture**, authored and scored here.
  They demonstrate the mechanism; they are **not** evidence about any real
  repository and **not** a universal performance claim. Results are specific to
  this benchmark.
- N is small (41 pairs); the bootstrap confidence intervals are **in-fixture**
  (resampling noise on this battery), not a generalization bound.
- C4 (pytest-subprocess) checkers are excluded from the benchmark for
  hermeticity; C1, C3, and C5 are exercised.
- `--extract` remains experimental and draft-only; the real-document metamorphic
  gate (`docs/REAL_DOC_METAMORPHIC_GATE.md`) is the pre-registered, label-free
  promotion/rejection instrument for extraction and is unchanged here.

## Unchanged

The full local loop, checker families, trust-state folding, audit export,
downstream recall, content-free sidecars, scope lint, and the GitHub Action
(trusted/internal repositories recommended) are unchanged. Benchmark
contributions must remain aggregate numbers only — never private repository
content.
