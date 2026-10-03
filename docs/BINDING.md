# Binding: a re-check trigger, not a behavior proof

Binding decides *when* a claim is re-checked; the checker decides *whether* it is true. This page
keeps the two layers apart and records the benchmark that measures each one separately. It is the
long version of the honest limits in the
[README](../README.md#what-it-checks-and-what-it-does-not).

## Binding is a re-check trigger, not a behavior proof

When a claim mentions a Python symbol defined in exactly one file, `dorian` also **watches that
defining file** — so a change there *re-checks* the claim, even when no checker named that file. This
closes a silent-skip gap, but it is the honest half of the story: **binding widens when a claim is
re-checked; the checker still decides whether it's true.** A watched file changing never makes a claim
`BROKEN` by itself.

The same trigger-coverage idea extends to behavior claims backed by a `pytest:` test. A C4 test proves
behavior *when it runs*, but its sealed watch used to be only the test file — so an edit to the
implementation the test imports could be silently skipped. `dorian` now statically parses the test
file (stdlib `ast`, read-only — no import execution, no `sys.path` mutation) and also watches the
repo-local files it imports, so a source edit re-runs the existing test even when the claim text names
no uniquely indexed symbol. It is the same honest split: **the test still decides truth; an imported
file changing only triggers the re-check.** Ambiguity is skipped, not guessed, and it is **not** a
sandbox. The `dorian bench c4-import-binding` suite measures it: the pre-fix test-file-only watcher
selects **0%** of implementation-only edits, the import-aware watcher **100%** of direct-import ones,
with zero false `BROKEN` from a behavior-preserving edit (the verdict tracks the test, not the file
change).

The binding-lifecycle benchmark measures exactly that split over **808 (artifact, mutation) pairs**
across 63 invented domains, with two mechanically-frozen labels per edit — *should re-check* and
*should alarm*:

- **Re-check (trigger) coverage** rose from **0.54** selection recall for a pre-binding,
  checker-path-only watcher to **1.00** for binding — it re-checks **286** stale-trigger pairs the
  old watcher silently skipped — and it does so at higher precision (**1.00**) than the rejected
  "watch any file containing the token" shortcut (**0.92**).
- **Alarm (truth) precision stayed 1.00** (zero false `BROKEN` over all 808 pairs): the extra
  re-checks from benign churn pass quietly; `ERRORED` is reported separately and is never an alarm.
- **The ceiling is shown, not hidden.** On a "gutted-body" edit (the symbol still exists, its
  behavior changed), the binding fires the re-check but an existence checker yields **zero** `BROKEN`
  — only a behavior checker (a `pytest:` test) on the same edit catches it. Binding is trigger
  coverage, **not** behavior proof.
- **Ambiguity is skipped, not guessed.** A symbol defined in more than one file is left unwatched
  (a wrong watch is a false alarm); the benchmark scores that as an honest miss rather than crediting
  it as a win.

We also reproduced **public, still-open problem classes** offline as hermetic fixtures (the public
issue is the template; the fixture is invented). Of three reproductions: a renamed config filename
left in the docs and a flipped `InsecureSkipVerify` TLS flag both fold `BROKEN` (**solved**); a major-
version API rename is caught while a same-name return-type change on a sibling is **missed** — the same
trigger-vs-truth ceiling, on a real class (**partial**). Two further cases (documented from public
sources, not reproduced) are honest misses (**not_solved**). These are scoped reproductions of public
problem classes — not universal validation.

The 808-pair figures above were **measured at dorian 0.9.0** and are **historical**; the
current-version rerun (same protocol) is in [`docs/BENCHMARK_CURRENT.md`](BENCHMARK_CURRENT.md).
See [`docs/BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md) and
[`docs/REALWORLD_USECASES.md`](REALWORLD_USECASES.md) (protocols alongside each); reproduce with
`dorian bench binding-lifecycle` and `dorian bench realworld-usecases`.

## See also

- [`COMMANDS.md`](COMMANDS.md) — `dorian bindings` (diagnostics), `dorian bind-suggest` (preview
  the files `verify` would bind), `dorian rebind` (re-derive watches on an old warrant), and the
  `--binding-gate` / `--strength-gate` seal-time review gates.
- [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md) — the trigger-vs-truth vocabulary the docs use.
- [`WRITING_GOOD_CLAIMS.md`](WRITING_GOOD_CLAIMS.md) — worked good/bad claim pairs, including the
  gutted-body ceiling where an existence check is too weak.
- [`V1_SCOPE.md`](V1_SCOPE.md) — what V1 strengthening does and does not promise.
