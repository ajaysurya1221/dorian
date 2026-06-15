# dorian large controlled-mutation benchmark (v0.7.0)

> **HISTORICAL — measured at v0.7.0.** These numbers are evidence about the v0.7.0
> implementation, not current behavior. For the current-version rerun (same protocol,
> stamped with the measured commit) see [`BENCHMARK_CURRENT.md`](BENCHMARK_CURRENT.md).
> Reproduce this suite at any version with `dorian bench large-mutation`.

Numbers only. Labels are **known-truth**: each mutation's stale / not-stale
outcome for a claim is a mechanical consequence of the edit (e.g. changing
`TIMEOUT = 30` to `10` falsifies the claim "the default timeout is 30 seconds").
The expected outcome is fixed by the edit itself, before measurement - no review
step and no opinion enters the labels. Reproduce with
`python -m bench.large_mutation` (or `dorian bench large-mutation`).

## What this is - and is not

A reproducible **demonstration on invented, synthetic fixtures** (the fixtures,
mutations, and labels are all authored here). It shows how claim-level
revalidation and file-change watching diverge under known edits - a property of
the mechanism. It is **not** evidence about any real repository and **not** a
universal performance claim. Results are specific to this benchmark. C4
(pytest-subprocess) checkers are excluded for hermeticity; C1, C3, and C5 are
exercised.

## Composition

- 6 fixture domains (python_service, csv_data, json_config, yaml_config, package_metadata, sql_data), 16 warranted artifacts, 53 claims.
- Checker styles exercised: C1-span, C3-path, C3-regex, C3-string, C3-string-brittle, C3-symbol, C5-domain, C5-freshness, C5-nullrate, C5-reconcile, C5-rowcount, C5-schema, C5-snapshot.
- 240 (artifact, mutation) pairs: 75 true-stale, 165 benign (19 of them neutral / unrelated-file, 9 adversarial).
- Errored pairs (a checker could not run): 0.

## Detectors

- **naive_file_watcher** - alarms if any *warranted source file* in the domain
  changed (the union of every artifact's referenced files; it ignores files no
  artifact references, so it is the crudest watcher over the warranted surface,
  not a literal whole-repo watcher).
- **path_scope_watcher** - alarms if any file this artifact's claims reference
  changed.
- **line_aware_watcher** - alarms only if a changed line range overlaps a claim's
  anchor lines (whole-file/data claims alarm on any change to their file; add/remove/rename alarm). The strongest strawman; rename-naive on purpose.
- **dorian** - alarms if `revalidate` marks any of the artifact's claims BROKEN.

## Aggregate results

| detector | TP | FP | FN | TN | precision (95% CI) | recall (95% CI) | F1 | spec. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| naive_file_watcher | 75 | 146 | 0 | 19 | 0.34 (0.28-0.40) | 1.00 (1.00-1.00) | 0.51 | 0.12 |
| path_scope_watcher | 75 | 58 | 0 | 107 | 0.56 (0.48-0.64) | 1.00 (1.00-1.00) | 0.72 | 0.65 |
| line_aware_watcher | 75 | 52 | 0 | 113 | 0.59 (0.51-0.67) | 1.00 (1.00-1.00) | 0.74 | 0.68 |
| dorian | 70 | 5 | 5 | 160 | 0.93 (0.87-0.99) | 0.93 (0.87-0.99) | 0.93 | 0.97 |

False-positive reduction (baseline FP / max(1, dorian FP)): **29.2x** vs naive (146 vs 5 FP), **11.6x** vs path-scope (58 vs 5), **10.4x** vs line-aware (52 vs 5).

Confidence intervals are bootstrap (1000 resamples, seed 42) and **in-fixture**:
they describe resampling noise on this battery, not generalization. Read them as
wide.

All three baselines show recall 1.00 **by construction**: a known-truth label only
fires when a watched file changed, and every file-change watcher alarms on that, so
no baseline can miss a true-stale pair here. The meaningful baseline axis is
therefore precision / specificity, not recall.

## By domain (dorian)

| domain | pairs | TP | FP | FN | TN | precision | recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| csv_data | 45 | 21 | 0 | 0 | 24 | 1.00 | 1.00 |
| json_config | 39 | 11 | 0 | 0 | 28 | 1.00 | 1.00 |
| package_metadata | 24 | 7 | 1 | 0 | 16 | 0.88 | 1.00 |
| python_service | 69 | 14 | 3 | 5 | 47 | 0.82 | 0.74 |
| sql_data | 24 | 8 | 0 | 0 | 16 | 1.00 | 1.00 |
| yaml_config | 39 | 9 | 1 | 0 | 29 | 0.90 | 1.00 |

## By mutation family (FP by detector; dorian TP/FN for context)

| family | pairs | path-scope FP | line-aware FP | dorian FP | dorian TP | dorian FN |
| --- | --- | --- | --- | --- | --- | --- |
| adversarial_comment_survival | 3 | 0 | 0 | 0 | 0 | 2 |
| adversarial_constant_survival | 3 | 0 | 0 | 0 | 0 | 2 |
| adversarial_docstring_survival | 3 | 1 | 0 | 0 | 0 | 1 |
| benign_data_value | 5 | 2 | 2 | 0 | 0 | 0 |
| comment_added | 11 | 5 | 3 | 0 | 0 | 0 |
| constant_added | 11 | 6 | 5 | 0 | 0 | 0 |
| data_append | 3 | 2 | 2 | 0 | 0 | 0 |
| data_emptied | 5 | 0 | 0 | 0 | 4 | 0 |
| data_reconcile_break | 6 | 0 | 0 | 0 | 2 | 0 |
| data_row_dropped | 8 | 1 | 1 | 0 | 6 | 0 |
| data_value_change | 14 | 4 | 4 | 0 | 8 | 0 |
| dependency_change | 6 | 0 | 0 | 0 | 3 | 0 |
| dependency_version_bump | 2 | 1 | 1 | 0 | 0 | 0 |
| file_deleted | 26 | 0 | 0 | 0 | 14 | 0 |
| file_renamed | 6 | 4 | 4 | 0 | 0 | 0 |
| key_removed | 6 | 1 | 1 | 0 | 3 | 0 |
| reorder | 9 | 5 | 5 | 0 | 0 | 0 |
| route_change | 12 | 3 | 2 | 0 | 5 | 0 |
| schema_field_dropped | 3 | 1 | 1 | 0 | 2 | 0 |
| schema_field_renamed | 5 | 1 | 1 | 0 | 3 | 0 |
| schema_field_retyped | 2 | 0 | 0 | 0 | 1 | 0 |
| schema_object_renamed | 2 | 0 | 0 | 0 | 1 | 0 |
| symbol_rename | 3 | 0 | 0 | 0 | 1 | 0 |
| type_annotation | 3 | 2 | 2 | 2 | 0 | 0 |
| unrelated_file | 19 | 0 | 0 | 0 | 0 | 0 |
| value_change | 46 | 9 | 8 | 0 | 17 | 0 |
| whitespace_reformat | 18 | 10 | 10 | 3 | 0 | 0 |

## Where dorian errs (honest failure modes)

- **False negatives** (5 pairs across 3 mutations): `py_items_to_docstring`, `py_login_to_comment`, `py_login_to_constant`.
  The cited path/literal is genuinely removed from its binding but survives verbatim
  elsewhere (a comment, docstring, or unused constant), so a substring scan still
  hits. This weakness is shared by `string:` **and un-anchored `regex:`** checkers -
  here it bites both a `string:/v1/login` and a bare `regex:/v1/login` claim, because
  `re.search` finds the path in the surviving comment. Switching string -> regex does
  **not** fix it; the real fix is a structurally anchored matcher (e.g. one anchored
  to the route-table key position), which this fixture does not author.
- **False positives** (5 pairs across 4 mutations): `pkg_py_whitespace`, `py_cfg_type_annotation`, `py_cfg_whitespace`, `yaml_rate_reformat`.
  Two mechanisms, both observed here: (1) brittle exact-`string:` claims break on any
  reformat (extra spaces, an inserted `: int` type annotation); (2) even the
  shape-tolerant `regex:TIMEOUT\s*=\s*30` breaks when a type annotation is inserted
  between the name and `=` (`TIMEOUT: int = 30`), since the colon defeats the
  name-to-operator adjacency. More tolerant or structurally anchored checker authoring
  narrows this; the brittle artifacts show the worst case. (A byte-exact `snapshot:`
  claim would also alarm on any edit to its file; that is a true-stale signal here,
  not one of these false positives.)

## Reading

dorian trades some recall for substantially higher precision: it suppresses the
benign-edit false alarms that make file-watching noisy (comments, reformatting,
reordering, renames, unrelated files), at the cost of misses when a claim is bound
by a substring scan (`string:` or un-anchored `regex:`) and the old literal survives
elsewhere. The precision gap holds against the line-aware watcher, not only the naive
one, though on this battery line-aware refines path-scope by only a few pairs (its
line-overlap gate rarely bites), so read the path-scope comparison as the stronger
claim. All figures are specific to this fixture suite.
