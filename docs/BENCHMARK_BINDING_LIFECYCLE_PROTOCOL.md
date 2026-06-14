# Binding-lifecycle benchmark — protocol

This is the **pre-measurement** protocol for `bench/binding_lifecycle.py`. It
describes what the benchmark measures and how labels are assigned, so the numbers
in [`BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md) (rendered
straight from machine output) can be read and reproduced without trusting the
author.

## What it measures

dorian's lifecycle promise — *a claim is verified at seal time and re-checked when
watched evidence changes* — for the **symbol → defining-file binding** fix and the
three Phase-0 precision nits. The binding fix widens the set of changes that
*re-check* a claim: a change to the file that **defines** a symbol the claim
mentions now makes the claim a revalidation candidate, even when no checker named
that file.

The benchmark is built to keep one distinction honest end to end:

> **Binding widens the re-check TRIGGER. It does not prove behavior.** A watched
> file changing makes a claim a *candidate*; the claim's own checker still decides
> the verdict. A claim is **never** BROKEN merely because a watched file changed.

## Two truth labels (the core of the design)

A checker-fact break always lives in a file the checker reads, so a
checker-path-only watcher never misses it — the binding fix's value is catching
**definer** changes the checker does *not* read. Expressing that honestly needs
two mechanically-frozen labels per mutation:

| label | meaning | scores |
|---|---|---|
| `breaks_trigger` | claim ids whose **true dependency** the edit touches (a checker file, or a file defining a symbol the claim is about). "Should be RE-CHECKED." | the **selection** layer |
| `breaks_fact` | claim ids whose **checker-verifiable fact** the edit falsifies. "Should ALARM (BROKEN)." Subset of `breaks_trigger`. | the **verdict** layer |

Both sets are authored in `bench/binding_lifecycle_domains.py` **before** any run,
as a mechanical consequence of the edit (e.g. "we renamed the symbol in its
definer, so the truth artifact's `symbol:` checker fails → it is fact-stale; the
trigger artifact's consumer string is untouched → it is trigger-stale but not
fact-stale"). **No human, model, or panel judgment enters a label**, and the
label never depends on dorian's output (a test pins this).

## The two layers and their detectors

**Selection (trigger) layer** — scored vs `breaks_trigger`:

| detector | alarms when |
|---|---|
| `naive_file_watcher` | any of the domain's source files changed |
| `checker_path_watcher` | a file a claim's **checker names** changed — dorian *before* the binding fix (the pre-binding ablation) |
| `bound_dorian_candidate` | revalidate **selected** a claim for re-check (the sealed watch, including the symbol-definer, was hit) |
| `overbroad_symbol_watcher` | **any** file containing a mentioned identifier changed — the rejected "any file with the token" shortcut, included only as a **cautionary** baseline |

**Verdict (truth) layer** — scored vs `breaks_fact`:

| detector | alarms when |
|---|---|
| `bound_dorian_broken_alarm` | revalidate marked a claim **BROKEN**. ERRORED is reported separately and is **never** an alarm. |

Candidate selection and final alarm are reported in **separate tables**. A benign
definer change is correctly *selected* (re-checked) without becoming an *alarm* —
candidate noise is not alarm noise, and a "selected but still VERIFIED" pair is
never counted as a false BROKEN.

## Strata

Every pair is labelled by **binding type** (per claim) and **mutation type** (per
edit), and metrics are sliced by both:

- binding types: `snake_function`, `async_function`, `camel_class`, `trigger_only`,
  `ambiguous_symbol`, `pyproject_script`, `ambiguous_pyproject_script`,
  `backtick_ident`, `backtick_common_word`, `c4_whitespace`, `semantic_ceiling`,
  `behavior_checked`, `bad_python_present`, `prose_only`.
- mutation types: `rename_definer`, `delete_definer`, `move_definer`,
  `benign_comment`, `benign_edit`, `neutral_unrelated`, `checker_fact_break`,
  `ambiguous_definer_change`, `binding_definer_change`,
  `backtick_common_word_change`, `gutted_body`.

## Phase-0 hardening covered

- **C4 nodeid whitespace** — a `pytest:` checker with whitespace around the nodeid
  binds and revalidates correctly (no spurious `trigger-only-symbol` flag).
- **Backticked common word** — a one-definer symbol named like a common word
  (`config`) is **not** bound from backtick markup, so changing its file does not
  select the claim.
- **Ambiguous pyproject script** — a console-script target that resolves to two
  modules is **not** auto-bound.

## The semantic ceiling, surfaced not solved

A `gutted_body` edit keeps the symbol but inverts behavior. The same edit is
scored against two artifacts:

- an **existence** checker (`symbol:`) — fires the trigger (candidate) but cannot
  prove the behavior change, so it produces **no BROKEN**. This is the documented
  ceiling, not a binding failure and not a semantic catch.
- a **behavior** checker (`pytest:`) — on the *same* edit, **does** break.

The benchmark reports both, and a test asserts the existence checker yields zero
BROKEN on the gutted body — so the numbers can never be read as a behavior catch.

## Mechanical labels & ground truth

A pair is `fact-stale` iff `breaks_fact` intersects the artifact's claim ids;
`trigger-stale` iff `breaks_trigger` does. Labels are frozen by the mutation spec,
never by dorian's verdict. The conservative skips are scored **honestly against
the user's intent**, not flattered:

- an **ambiguous-symbol** definer change is labelled trigger-stale (the symbol *is*
  the claim's subject), so dorian's deliberate skip shows up as a
  `bound_candidate` **miss** — the real cost of avoiding false precision, surfaced
  not hidden.
- a **backticked common word** is *not* a symbol reference (markup), so changing a
  same-named function is correctly *not* a dependency — `bound_candidate` correctly
  does not select it.

## Determinism & content safety

- The committed summary is byte-identical across runs: no sha, warrant id,
  wall-clock timestamp, or host path is ever emitted. Every broken / errored /
  candidate warrant id is mapped to its stable artifact uri before any record is
  built. Provenance is a content digest of the fixtures plus a deterministic run
  id. (`measured_commit` is the dorian commit the fixtures were run against —
  stamped by the CLI, the one intentional sha.)
- Bootstrap 95% CIs: 1000 resamples, fixed seed 42, labelled **in-fixture only**.
  Raw counts are reported beside every ratio.

## Reproduce

```bash
dorian bench binding-lifecycle            # full suite
dorian bench binding-lifecycle --quick    # the deterministic CI subset
```

## Wording caveats

These are **known-truth controlled mutations** on **invented, public-safe**
fixtures: a reproducible demonstration of the *mechanism* on *this suite*, not
evidence about any real repository. The benchmark does not claim the result is
proven, validated, universal, production-grade, or real-world validated, and it
never claims binding is a semantic catch — only that it improves **trigger
coverage**, while the checker decides truth.
