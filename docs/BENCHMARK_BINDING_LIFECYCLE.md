# dorian binding-lifecycle benchmark

> **HISTORICAL — measured at dorian 0.9.0** (see the run header below; the preserved 808-pair
> full run). Evidence about the 0.9.0 implementation, not current behavior. The current-version
> rerun (1.0.0rc1, identical results — see [`BENCHMARK_CURRENT.md`](BENCHMARK_CURRENT.md)) confirms
> the V1 changes did not regress it. NOTE: `dorian bench binding-lifecycle` REGENERATES this file;
> restore it from git after a rerun so the historical record survives.

> Generated from machine output by `bench.binding_lifecycle`. Known-truth labels,
> in-fixture results — a reproducible demonstration of the MECHANISM on this suite,
> not evidence about any real repository.

## Scope

- schema `dorian-binding-lifecycle-v1` · dorian `0.9.0` · run_id `168b50d9aa631d52`
- 63 domains · 122 artifacts · 122 claims · 408 mutations · 808 (artifact, mutation) pairs
- 174 fact-stale · 631 trigger-stale · 177 benign · 0 errored pairs

Two truth labels: **breaks_trigger** (should be re-checked) scores the selection
layer; **breaks_fact** (should ALARM) scores the verdict layer. A definer change is
trigger-stale without being fact-stale — that is the whole point.

## Selection (trigger) layer — flagged for re-check? (scored vs breaks_trigger)

| watcher | TP | FP | FN | precision (95% CI) | recall (95% CI) | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| naive_file_watcher | 631 | 177 | 0 | 0.78 (0.75-0.81) | 1.00 (1.00-1.00) | 0.88 |
| checker_path_watcher | 343 | 0 | 288 | 1.00 (1.00-1.00) | 0.54 (0.50-0.58) | 0.70 |
| bound_dorian_candidate | 629 | 0 | 2 | 1.00 (1.00-1.00) | 1.00 (0.99-1.00) | 1.00 |
| overbroad_symbol_watcher | 628 | 56 | 3 | 0.92 (0.90-0.94) | 1.00 (0.99-1.00) | 0.96 |

## Verdict (truth) layer — marked BROKEN? (scored vs breaks_fact)

| alarm | TP | FP | FN | precision (95% CI) | recall (95% CI) | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| bound_dorian_broken_alarm | 174 | 0 | 0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) | 1.00 |

ERRORED is reported separately, never an alarm: 0 pair(s).

## False-TRUSTED reduction (the binding fix's point — TRIGGER level)

- selection recall on the 631 trigger-stale pairs: checker_path (pre-binding) **0.54** -> bound_candidate **1.00**
- trigger-stale pairs checker_path SILENTLY SKIPS but binding RE-CHECKS: **286**

## Semantic ceiling (trigger != truth) — surfaced, not solved

- gutted-body + existence checker: 1 pairs, candidate sel-recall **1.00**, BROKEN alarms **0**
- SAME edit + behavior (C4) checker: 1 pairs, BROKEN recall **1.00**
- an existence/shape checker fires the TRIGGER on a gutted body but cannot prove the behavior change (no BROKEN) — the documented ceiling, NOT a binding failure and NOT a semantic catch; only a checker that EXERCISES behavior catches it

## By binding type

| binding_type | pairs | checker_path sel-recall | bound_cand sel-recall | bound_broken precision | bound_broken recall |
| --- | --- | --- | --- | --- | --- |
| ambiguous_pyproject_script | 4 | 0.50 | 0.50 | n/a | n/a |
| ambiguous_symbol | 2 | 0.50 | 0.50 | 1.00 | 1.00 |
| async_function | 119 | 1.00 | 1.00 | 1.00 | 1.00 |
| backtick_common_word | 2 | n/a | n/a | n/a | n/a |
| backtick_ident | 2 | 0.00 | 1.00 | n/a | n/a |
| bad_python_present | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| behavior_checked | 2 | 0.00 | 1.00 | 1.00 | 1.00 |
| c4_whitespace | 2 | 0.00 | 1.00 | 1.00 | 1.00 |
| camel_class | 133 | 1.00 | 1.00 | 1.00 | 1.00 |
| prose_only | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| pyproject_script | 4 | 0.50 | 1.00 | 1.00 | 1.00 |
| semantic_ceiling | 2 | 1.00 | 1.00 | n/a | n/a |
| snake_function | 140 | 1.00 | 1.00 | 1.00 | 1.00 |
| trigger_only | 392 | 0.17 | 1.00 | 1.00 | 1.00 |

## By mutation type (verdict precision / recall)

| mutation_type | pairs | bound_broken precision | bound_broken recall |
| --- | --- | --- | --- |
| ambiguous_definer_change | 3 | n/a | n/a |
| backtick_common_word_change | 2 | n/a | n/a |
| benign_comment | 115 | n/a | n/a |
| benign_edit | 112 | n/a | n/a |
| binding_definer_change | 2 | n/a | n/a |
| checker_fact_break | 117 | 1.00 | 1.00 |
| delete_definer | 112 | 1.00 | 1.00 |
| gutted_body | 2 | 1.00 | 1.00 |
| move_definer | 112 | n/a | n/a |
| neutral_unrelated | 116 | n/a | n/a |
| rename_definer | 115 | 1.00 | 1.00 |

## Reproduce

```bash
dorian bench binding-lifecycle            # full
dorian bench binding-lifecycle --quick    # CI subset
```

