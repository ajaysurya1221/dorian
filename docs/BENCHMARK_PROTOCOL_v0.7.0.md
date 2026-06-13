# dorian v0.7.0 large controlled-mutation benchmark - pre-measurement protocol

This protocol fixes the design **before** the numbers are produced. It defines
what is measured, how labels are determined, which metrics are reported, and what
may and may not be claimed. It contains **no results** and **no pass/fail gate**:
the benchmark publishes aggregate numbers and lets them speak. The rendered
results live in [`BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md); the machine outputs
in `bench/results/`.

Reproduce with `python -m bench.large_mutation` (or `dorian bench large-mutation`).

## Scope

One scoped property is under test:

> **dorian suppresses noisy benign-change alarms when claims are well-warranted**,
> while its own misses and false alarms are measured rather than assumed.

This is a **mechanism demonstration on invented, synthetic fixtures**, not evidence
about any real repository. The benchmark deliberately includes cases dorian gets
wrong (brittle checkers, substring survival) so the published numbers are not a
flattering 1.0.

Out of scope (and never claimed): that dorian detects every stale claim, that it
is generally better than all alternatives, that it is real-world validated or
validated by any form of manual, assisted, or ensemble review, or that v0.7.0
carries any benchmark number not produced by this run.

## Ground-truth rule (known-truth labels)

Labels are **mechanically determined from controlled edits**, never from opinion:

- A claim is **broken** by a mutation iff the claim's underlying FACT is falsified
  by the edit (e.g. changing `TIMEOUT = 30` to `10` falsifies "the timeout is 30").
- An (artifact, mutation) pair is **stale** iff the mutation breaks at least one of
  that artifact's claims; otherwise **benign**.
- **neutral** pairs (a mutation that touches only an unrelated file) are a labelled
  subset of benign and are reported separately; they are NOT excluded from the
  denominators (a real watcher faces them).
- The frozen label is the set `MutationSpec.breaks`. dorian's verdict is **measured**
  against it; a disagreement is a true/false positive/negative, never a reason to
  relabel.

No label is produced by manual inspection, an assistant, a model ensemble, or any
adjudication step; every label is a mechanical consequence of the edit.

## Fixture domains

Six invented, public-safe, hermetic domains, each a separately sealed git repo:

| domain | sources | checker styles exercised |
| --- | --- | --- |
| python_service | auth/config/routes `.py` | C1 span, C3 symbol/regex/string/path |
| csv_data | CSV datasets + a mirror | C5 rowcount/schema/domain/nullrate/freshness/reconcile/snapshot |
| json_config | JSON settings/secrets | C3 regex/string/path |
| yaml_config | YAML deploy/limits | C3 regex/string/path |
| package_metadata | `package.json` + a version module | C3 regex/string/path |
| sql_data | `.sql` DDL + CSV + a SQLite db | C5 reconcile (csv~~sqlite)/rowcount/domain, C3 string/regex/path |

Each domain has two or more warranted artifacts, including at least one authored
with deliberately **brittle** checkers (exact-string / byte-exact snapshot) to
surface dorian's worst-case false positives on purpose.

Inclusion/exclusion:
- Public, invented inputs only; no private repo names, paths, or content; no network.
- C4 (pytest-subprocess) checkers are excluded for hermeticity.
- Every claim must seal **green** at t0 (the seal pipeline refuses on any failed or
  errored checker), so a mis-authored fixture fails loudly instead of scoring a
  vacuous pass.

## Mutation families

Stale families include: value change, symbol/field rename, route change, file
deletion, schema field change, data row drop, data value change, data emptied,
data reconcile break. Adversarial stale families (the literal survives elsewhere):
comment / docstring / unused-constant survival. Benign families include: comment
added, whitespace reformat, type annotation added, constant/field added,
reordering, file rename, dependency-version bump, benign data value, data append.
Neutral: unrelated-file change.

## Baselines (three, each strictly refining the last)

1. **naive_file_watcher** - alarm iff any of the domain's source files changed
   (crudest project-wide watcher).
2. **path_scope_watcher** - alarm iff any file the artifact's claims reference changed.
3. **line_aware_watcher** - alarm iff a changed line range overlaps a claim's anchor
   lines (whole-file/data claims alarm on any change to their file; add/remove/rename
   alarm). Rename-naive on purpose; the strongest strawman a careful engineer builds.

By construction `naive >= path_scope >= line_aware` (alarm sets nest). Baselines are
defined honestly and not weakened below their stated definition. dorian is the fourth
detector: alarm iff `revalidate` marks any of the artifact's claims BROKEN (ERRORED is
never an alarm).

## Metrics

Per detector, over all pairs and per stratum: TP, FP, FN, TN, precision, recall,
F1, specificity, false-positive rate, alarm rate. Plus false-positive reduction
(`baseline_FP / max(1, dorian_FP)`) reported **with raw FP counts**, and recall is
reported alongside so precision gains are not read in isolation.

Precision/recall with an empty denominator are defined as `1.0` (reused from
`bench/metrics.py`); this can only affect strata with no positives/alarms and is
disclosed.

**Stratified** metrics: by domain, by mutation family, by artifact, and an
adversarial-only slice. Raw counts accompany every ratio.

Confidence intervals: bootstrap, **1000 resamples, fixed seed 42**, reusing the
suite's `metrics.prf` / `_ci`. They are explicitly labelled **in-fixture** - they
describe resampling noise on this battery, not generalization beyond it.

Errored pairs (a checker could not run) are counted and reported separately; an
ERRORED claim is never scored as an alarm.

## Output files

- `bench/results/v0.7.0_large_controlled_mutation_summary.json` - aggregate +
  stratified metrics, composition, provenance, error attribution.
- `bench/results/v0.7.0_large_controlled_mutation_records.jsonl` - one row per
  (artifact, mutation) pair: domain, artifact, mutation, family, expected label,
  expected broken claim ids, all four detector outputs, dorian's broken/errored
  claim ids, changed files, checker styles.
- `docs/BENCHMARK_v0.7.0.md` - the rendered public summary (numbers only).

These are produced **only by running this benchmark**; no v0.6.0 number is copied
into them. The v0.6.0 `bench/controlled_mutation.py` benchmark and its
`docs/BENCHMARK_v0.6.0.md` remain as the earlier, smaller measurement and are not
edited except to note they are historical.

## Determinism and provenance

Fixed git identities/dates make commit shas stable; output is sorted JSON; the
deterministic core (`run_benchmark`) embeds no wall-clock time. Provenance carries
the dorian **version**, a deterministic **run id** (a digest over the schema +
fixture manifest, not a clock), the bootstrap seed, and a **fixture manifest digest**
(bare hex). The measured dorian-repo commit is recorded as **bare hex** by the CLI
(not a `sha256:` value, so it neither trips the leakage gate nor enters the
deterministic core). No timestamps, warrant ids, or host paths reach any committed
artifact.

## Wording

Allowed: "known-truth controlled mutations", "mechanically determined labels",
"aggregate / benchmark-specific results", "measured on N pairs", "FP reduction X at
recall Y", "results are specific to this benchmark", "in-fixture bootstrap interval".

Forbidden in any public output (README, docs, tests, benchmark JSON/JSONL, rendered
summary): any wording that attributes the benchmark's labels or evidence to manual
inspection, the maintainer, an AI assistant, a model ensemble, an adjudication step,
or a blinded scoring step - and the overclaims proven, validated, real-world
validated, universal, and production-grade. The product may still describe the
AI-generated artifacts dorian warrants; the ban is on benchmark-EVIDENCE provenance.
(The concrete banned tokens are enforced by the grep gates and the wording test in
tests/test_large_mutation.py, which assembles them from fragments so the enforcement
itself stays grep-clean.)
