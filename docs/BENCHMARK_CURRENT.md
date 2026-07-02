# Current-version benchmark results

Version-stamped reruns of dorian's reproducible benchmark suites on the **current** code,
so the published numbers track the implementation rather than lagging behind it. The older
result docs ([`BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md) = v0.7.0,
[`BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md) = 0.9.0) are **historical**
and are kept as-is for provenance.

## Measurement environment

| field | value |
| --- | --- |
| dorian version | `1.4.0` |
| metric commit | `33e9eaf` (the benchmark figures were measured here, during the release audit) |
| release commit | `81cebbc` (1.0.1) → v1.0.2 announcement hotfix. The 1.0.1 changes (C4 leading-dash nodeid rejection, C5 reconcile per-query timeout, a byte-identical index-once `verify` refactor, the `suggest-claims` / `export --in-toto` commands) plus the v1.0.2 hotfix (export `.warrant` filename disambiguation, `suggest-claims` PEP 263 encoding read, a `symbol_index` non-git `GitError` guard, and CI/SCA/credential/doc hardening) touch no checker numeric behavior; both suites below were **re-run at 1.0.2 and reproduce the metric-commit figures exactly** — binding-lifecycle to the same content-derived `run_id` `168b50d9aa631d52` — so these changes do not move what the suites measure. v1.1.0 added the `dorian init` scaffolder, the PR-comment renderer enhancements (a status line, trust-change counts, sealed-at, and remediation), and build/VCS guards against editor/file-sync `… 2.py` duplicate files (untracked local artifacts — never tracked, never in a CI wheel or on PyPI); v1.1.1 makes the `dorian init` starter claim load-bearing (a scaffold default). All of this is a new command plus output formatting, scaffold defaults, and packaging hygiene only — touching no checker/binding/fold code — so the figures stand unchanged at 1.1.1 (the suites were last executed at 1.0.2, not re-run since). **v1.2.0** adds C4 import-aware binding (a trigger-axis watch widening that affects only C4 `pytest:` claims — not the C1/C3/C5 symbol/regex/string/path/data paths these suites exercise) and the opt-in, default-off `--strength-gate` (advisory; changes no checker verdict or binding). All three suites were **re-run at v1.2.0 and reproduce the metric-commit figures exactly** — binding-lifecycle again landing on the same content-derived `run_id 168b50d9aa631d52` — so 1.2.0 does not move what they measure. **v1.3.0** adds the Claude Code claim-warrants scaffolder (`dorian claude-code install-claim-warrants`: a new CLI subcommand, packaged skill/hook/settings templates, an opt-in reminder Stop hook, and docs) — a CLI/packaging/docs addition that touches **no checker, binding, or fold code**, so the figures stand unchanged at 1.3.0 (the suites were last executed at v1.2.0, not re-run since). **v1.4.0** adds the Dorian Loop Guard (`dorian loop preflight|prompt|install`) and the governance foundation (`dorian goal`/`gate`/`governance install`, the atomic sidecar writer, the deterministic-core import-firewall test) — loop-steering/preflight commands, host-adapter templates, and docs that touch **no checker, binding, or fold code** — so the figures stand unchanged at 1.4.0 (the suites were last executed at v1.2.0, not re-run since) |
| Python | 3.12.4 |
| platform | darwin (CI matrix: 3.11 / 3.12 / 3.13) |
| reproduce | `dorian bench large-mutation` · `dorian bench binding-lifecycle` · `dorian bench realworld-usecases` |

These numbers were re-run at the `1.0.0rc1` commit after the adversarial-review fixes landed,
again during the independent release audit, and again at `1.0.1` — each time reproducing the
metric-commit figures unchanged (the binding-lifecycle rerun lands on the same content-derived
`run_id 168b50d9aa631d52`, a byte-identical result). The suites exercise C1/C3
(symbol/regex/string/path) and C5, not malformed-nodeid, pathological-query, or the
structural/config-binding paths, so the `1.0.1` checker fixes and the two additive commands do
not — and did not — move them. The version stamp keeps this current-version doc aligned with the
source package version without upgrading the benchmark claim beyond the recorded metric-run
evidence.

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
