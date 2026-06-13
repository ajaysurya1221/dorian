# dorian controlled-mutation benchmark (v0.6.0)

Numbers only. Labels are **known-truth**: each mutation's stale / not-stale
outcome is a mechanical consequence of the edit (e.g. changing `TIMEOUT = 30`
to `10` falsifies the claim "the default timeout is 30 seconds"). The expected
outcome is fixed by the edit itself, before measurement — no review step and no
opinion enters the labels. Reproduce with `python -m bench.controlled_mutation`
(or `dorian bench mutation`).

## What this is — and is not

This is a reproducible **demonstration on a single invented, synthetic fixture**
(the fixture, the mutations, and the labels are all authored here). It shows how
claim-level revalidation and file-change watching diverge under known edits — a
property of the mechanism. It is **not** evidence about any real repository and
**not** a universal performance claim. Results are specific to this benchmark.
C4 (pytest-subprocess) checkers are excluded for hermeticity; C1, C3, and C5 are
exercised.

## Composition

- Fixture: 2 warranted artifacts, 9 claims, 6 files.
- 41 (artifact, mutation) pairs: 19 true-stale, 22 benign/neutral.
- Errored pairs (checker could not run): 0.

## Detectors

- **naive_file_watcher** — alarms if any watched file changed.
- **line_aware_watcher** — alarms only if a changed line range overlaps a claim's
  anchor lines (whole-file/data claims alarm on any change to their file). The
  stronger strawman a careful engineer would build; rename-naive on purpose.
- **dorian** — alarms if `revalidate` marks any of the artifact's claims BROKEN.

## Results

| detector | TP | FP | FN | TN | precision (95% CI) | recall (95% CI) |
| --- | --- | --- | --- | --- | --- | --- |
| naive_file_watcher | 19 | 20 | 0 | 2 | 0.49 (0.33-0.65) | 1.00 (1.00-1.00) |
| line_aware_watcher | 19 | 15 | 0 | 7 | 0.56 (0.38-0.72) | 1.00 (1.00-1.00) |
| dorian | 16 | 5 | 3 | 17 | 0.76 (0.56-0.95) | 0.84 (0.67-1.00) |

False-positive reduction (baseline FP / max(1, dorian FP)): **4.0x** vs the naive watcher (20 vs 5 false positives), **3.0x** vs the line-aware watcher (15 vs 5).

Confidence intervals are bootstrap (1000 resamples, seed 42) and **in-fixture**:
with 41 pairs over one fixture they describe resampling noise on this
battery, not generalization. Read them as wide.

## dorian by artifact

| artifact | pairs | TP | FP | FN | TN | precision | recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `docs/design.md` (shape-tolerant claims) | 32 | 13 | 2 | 3 | 14 | 0.87 | 0.81 |
| `docs/design-naive.md` (brittle exact-string claim) | 9 | 3 | 3 | 0 | 3 | 0.50 | 1.00 |

## Where dorian errs (honest failure modes)

- **False negatives** (3): `routes_login_to_comment`, `routes_login_to_constant`, `routes_login_to_docstring`. dorian's `string:` checker passes
  when the cited literal survives elsewhere (a comment, docstring, or unused
  constant) while the real binding changed — a substring-match weakness. An
  anchored `regex:` or `symbol:` checker would catch these.
- **False positives** (5): `cfg_fact_relocated`, `cfg_type_annotation_added`, `cfg_whitespace_reformat`. Exact-string and tightly-anchored
  regex checkers alarm on reformatting (extra spaces, a type annotation) or when a
  fact is relocated to another file — the value is still correct. More tolerant
  checker authoring narrows this; the brittle `docs/design-naive.md` claim shows
  the worst case.

## Reading

dorian trades some recall for substantially higher precision: it suppresses the
benign-edit false alarms that make file-watching noisy (comments, reformatting,
reordering, renames, unrelated columns), at the cost of misses when a claim is
bound by a substring checker. The precision gap holds against the line-aware
watcher, not only the naive one. All figures are specific to this fixture.
