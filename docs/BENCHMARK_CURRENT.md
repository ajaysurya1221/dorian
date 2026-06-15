# Current-version benchmark results

Version-stamped reruns of dorian's reproducible benchmark suites on the **current** code,
so the published numbers track the implementation rather than lagging behind it. The older
result docs ([`BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md) = v0.7.0,
[`BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md) = 0.9.0) are **historical**
and are kept as-is for provenance.

## Measurement environment

| field | value |
| --- | --- |
| dorian version | `1.0.0rc1` (V1 release candidate) |
| metric commit | `b7376e7` (the benchmark figures were measured here) |
| release commit | the tagged `v1.0.0rc1` commit is a later **docs/release-hygiene only** commit; `git diff b7376e7..<tag> -- src bench` is empty, so the figures apply unchanged |
| Python | 3.12.4 |
| platform | darwin (CI matrix: 3.11 / 3.12 / 3.13) |
| reproduce | `dorian bench large-mutation` · `dorian bench binding-lifecycle` · `dorian bench realworld-usecases` |

These numbers were re-run at the `1.0.0rc1` commit *after* the adversarial-review fixes
landed AND again during the independent release audit, confirming those fixes (py-const type
check, `code:` docstring handling, config-key stopwords) did not move the benchmark figures —
expected, since the suites exercise C1/C3 (symbol/regex/string/path)/C5, not the new
structural/config-binding paths. Commits between the metric commit and the release tag change
only docs/release hygiene, never checker or benchmark logic.

## Results

### Large controlled-mutation (240 pairs, 6 synthetic domains)

```
dorian: precision 0.93 / recall 0.93
file-change watchers: recall 1.00 / precision 0.34 (naive), 0.56 (path-scope), 0.59 (line-aware)
false-positive reduction: 11.6x vs path-scope (58 -> 5), 10.4x vs line-aware (52 -> 5)
```

**Identical to the v0.7.0 historical figures** — the V1 additions (structural checkers,
semantic-context search, config-key binding, checker-strength diagnostics, trusted-base mode)
are additive and do **not** regress this suite.

### Binding-lifecycle (808 pairs, 63 synthetic domains, two mechanically-frozen labels)

```
selection (trigger) recall: checker_path_watcher 0.54 -> bound_dorian_candidate 1.00
  (286 trigger-stale pairs re-checked that the pre-binding checker-path watcher silently skips)
selection precision: bound_dorian_candidate 1.00 (vs 0.92 for the rejected "watch any file with the token")
verdict (alarm) precision/recall: 1.00 / 1.00 (174/174 fact-stale pairs), 0 false BROKEN over all 808
errored pairs: 0 (ERRORED is reported separately, never an alarm)
gutted-body ceiling: existence checker fires the trigger but yields 0 BROKEN; only a C4 test catches it
```

**Identical to the 0.9.0 historical run** (same content-derived `run_id 168b50d9aa631d52`) — again
confirming the V1 changes did not move the binding-lifecycle numbers.

### Real-world public-case reproductions (5 cases, offline hermetic fixtures)

```
solved 2 · partial 1 · not_solved 2
```

Scoped reproductions of public problem *classes* (the public issue is the template; the fixture
is invented), **not** broad real-world validation.

### Warrant-quality harness (new in V1)

`dorian bench warrant-quality <artifact>` scores, per claim and offline, whether the checker catches
the drift it implies (caught / missed / brittle / ceiling), separating the trigger layer from the
verdict layer and keeping ERROR distinct from a miss. It is an evidence generator about *a specific
warrant*, not a repo-level metric; see [`V1_SCOPE.md`](V1_SCOPE.md).

## What these results prove — and what they do not

**Allowed (per [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md)):**

- the mechanism **reproduces** on the named synthetic suites at the stamped version and commit;
- on those inputs, claim-level revalidation has far fewer false re-checks than a file watcher, and
  binding's trigger recall is near-complete with zero false BROKEN;
- the V1 changes did **not regress** the prior numbers (the reruns match the historical runs).

**NOT supported:**

- "works on real repos in general" / "validated" / "production-grade" — these are synthetic suites;
- that the numbers transfer to your codebase;
- that binding proves semantic behavior — it widens the re-check trigger; the checker decides truth
  (the gutted-body ceiling is shown, not solved).
