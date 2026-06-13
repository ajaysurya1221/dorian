# dorian v0.7.1 — large controlled-mutation benchmark

v0.7.1 widens the project's public benchmark evidence. It adds a larger
known-truth controlled-mutation benchmark spanning six fixture domains and three
file-change-watcher baselines, and points the README at it as the current
numbers. No runtime behavior changes: the warrant, checker, seal, and revalidate
code is unchanged, so the benchmark is *named* for the v0.7.0 feature set it
exercises while shipping in this v0.7.1 release.

## What's new

- **`docs/BENCHMARK_v0.7.0.md` + `dorian bench large-mutation`** — a known-truth
  controlled-mutation benchmark over **six** invented, synthetic fixture domains
  (Python service, CSV data, JSON config, YAML config, package metadata, SQL
  data), **16** warranted artifacts, **53** claims, **240** (artifact, mutation)
  pairs. Each mutation's stale / not-stale label is a **mechanical consequence of
  the edit**, frozen before measurement — no review judgment of any kind. It
  compares dorian's claim-level revalidation against **three** file-change
  watchers that strictly nest (naive warranted-surface, path-scope, and a
  line-aware diff-hunk watcher) and reports the full confusion matrix,
  precision/recall/F1/specificity with in-fixture bootstrap CIs, false-positive
  reduction (with raw counts), per-domain / per-family / per-artifact / adversarial
  stratification, and dorian's own false positives and false negatives.
- **`docs/BENCHMARK_PROTOCOL_v0.7.0.md`** — the pre-measurement protocol: scope,
  fixtures, mutation families, mechanical labeling rule, baselines, metrics,
  determinism, and allowed/forbidden wording. It declares no pass/fail gate; the
  benchmark publishes numbers and lets them speak.
- **Output is deterministic** (summary, records JSONL, and rendered markdown are
  byte-identical across runs); the committed summary carries only aggregate
  numbers, public fixture file names, mutation/claim ids, and a deterministic run
  id — no timestamps, warrant ids, or host paths.
- The earlier, smaller v0.6.0 benchmark (`dorian bench mutation`,
  `docs/BENCHMARK_v0.6.0.md`) is retained as a historical measurement.

## Benchmark numbers (measured on the committed fixture suite, 240 pairs, 0 errored)

| detector | TP | FP | FN | TN | precision | recall |
| --- | --- | --- | --- | --- | --- | --- |
| naive_file_watcher | 75 | 146 | 0 | 19 | 0.34 | 1.00 |
| path_scope_watcher | 75 | 58 | 0 | 107 | 0.56 | 1.00 |
| line_aware_watcher | 75 | 52 | 0 | 113 | 0.59 | 1.00 |
| dorian | 70 | 5 | 5 | 160 | 0.93 | 0.93 |

False-positive reduction: 11.6x vs the path-scope watcher (58 vs 5), 10.4x vs the
line-aware watcher (52 vs 5), 29.2x vs the naive watcher (146 vs 5). The three
baselines reach recall 1.00 **by construction** (a known-truth label only fires
when a watched file changed, which every file-change watcher alarms on), so the
meaningful baseline axis is precision. dorian trades some recall — five
substring-survival misses where a removed literal lingers in a comment, docstring,
or unused constant — for substantially higher precision; its five false positives
are brittle exact-string and inserted-type-annotation reformats, reported honestly.

## Caveats — read before relying on it

- These numbers describe a **synthetic fixture suite**, authored and scored here.
  They demonstrate the mechanism; they are **not** evidence about any real
  repository and **not** a universal performance claim. Results are specific to
  this benchmark.
- The benign side is larger than the true-stale side by construction (every
  mutation is scored against every artifact in its domain, as a watcher of that
  project would be); read precision and raw FP counts over specificity.
- Bootstrap confidence intervals are **in-fixture** (resampling noise on this
  battery), not a generalization bound.
- C4 (pytest-subprocess) checkers are excluded for hermeticity; C1, C3, and C5 are
  exercised.
- `--extract` remains experimental; the real-document metamorphic gate
  (`docs/REAL_DOC_METAMORPHIC_GATE.md`) is unchanged here.

## Unchanged

The full local loop, checker families, trust-state folding, audit export,
downstream recall, content-free sidecars, scope lint, and the GitHub Action
(trusted/internal repositories recommended) are unchanged. Benchmark
contributions must remain aggregate numbers only — never private repository
content.
