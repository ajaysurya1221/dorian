# Changelog

All notable changes to dorian (`dorian-vwp`) are recorded here. Full per-release notes live in
[`docs/releases/`](docs/releases/). The warrant format, checker grammar, exit codes, and trust
semantics have been stable since 1.0.0.

## [Unreleased]

C4 import-aware dependency binding. **No breaking changes** (a re-check *trigger* widening only;
warrant schema, checker grammar, exit codes, fold policy, and security posture are unchanged).

### Added
- **C4 import-aware binding** (`src/dorian/test_deps.py`). A `pytest:` checker proves behavior *when
  it runs*, but its sealed watch was only the nodeid's test file — so an edit to the implementation the
  test imports could be silently skipped at revalidation even though an adequate behavior checker
  existed (a re-check *trigger* gap, not a truth gap). `dorian verify` and `dorian rebind` now
  statically parse the test file (stdlib `ast`, read-only — **no import execution, no `sys.path`
  mutation, no package introspection, no network**) and add the tracked repo-local `.py` files it
  imports to the claim's watch and auto-captured read-set. A source edit then re-runs the existing C4
  checker; **the checker still decides truth** (a file change never marks a claim `BROKEN` by itself).
  Conservative: an import resolving to zero or to more than one tracked file is skipped, not guessed.
- **`dorian bench c4-import-binding`** — a deterministic, known-truth synthetic suite for the above:
  the pre-fix test-file-only watcher selects 0% of implementation-only edits, the import-aware watcher
  100% of direct-import ones, with zero false `BROKEN` from a behavior-preserving edit.
- **`dorian bind-suggest`** now reports a third provenance, `bind_test_deps` / `bind (test-dep)`, for
  the implementation files a claim's C4 test imports (content-free; paths only).

### Changed
- The `bindings` / `--binding-gate` `trigger-only-symbol` diagnostic now treats a C4 test's
  import-derived watches as **checker-exercised** (the test imports and runs them), so widening a
  behavior claim's watch never spuriously flags it — and `--binding-gate=fail` does not start refusing
  good C4 behavior claims.

## [1.1.1] — 2026-06-19

Golden-path polish. **No breaking changes** (a scaffold default only; verification, warrant format,
checker grammar, exit codes, and trust semantics are unchanged).

### Changed
- **`dorian init`'s starter claim is now load-bearing.** Previously it sealed as a non-load-bearing
  claim, so a later break folded the warrant to DEGRADED (exit 3) — which the scaffolded
  `fail_on: revoked` Action does not block on, letting a first broken promise silently ship. The
  starter is now load-bearing, so breaking it folds to **REVOKED (exit 4)** and the default Action
  **blocks the PR** — the golden path now demonstrates the gate it advertises. This also matches the
  scaffolded change note, which already described these as "load-bearing facts." Sealing is
  unaffected (the starter still seals green on a fresh `dorian verify`).

## [1.1.0] — 2026-06-18

Productization release — easier first run, clearer PR output, cleaner package. **No breaking
changes** (command surface and output formatting only; verification is unchanged).

### Added
- **`dorian init`** — first-run scaffolding: a born-verifiable starter `claims.json`, the change
  note it backs, and a `.github/workflows/dorian.yml` Action workflow. Writes files only (never runs
  a checker or executes code), confined to the repo root, idempotent, with `--force`, `--dry-run`,
  and the global `--json`.
- **Customer-readable PR comment** (`revalidate --format md`): an explicit `Status:` Blocked /
  Passed / Errored verdict, an aggregate trust-change counts table, a `sealed in <artifact>.warrant`
  line per affected artifact, and a verdict-keyed `What to do:` remediation line. The comment stays
  deterministic and keeps its content-carryover bound.

### Packaging
- Added a `.gitignore` rule and a Hatch build `exclude` so stray editor/file-sync `… 2.py`
  duplicate files can never be tracked or packaged into a wheel, even from a dirty working tree.
  (These were untracked local artifacts — never in a CI build or on PyPI.)

See [`docs/releases/v1.1.0.md`](docs/releases/v1.1.0.md).

## [1.0.2] — 2026-06-17

Announcement-readiness hotfix: PyPI coherence, immutable Action ref, an SCA-scope fix, and two
edge-case bug fixes (`export` of a `*.warrant`-named artifact; `suggest-claims` PEP 263 reads). See
[`docs/releases/v1.0.2.md`](docs/releases/v1.0.2.md).

## [1.0.1] — 2026-06-17

Added `suggest-claims` (C3 scaffolds) and `export --in-toto`; C4/C5 edge-case fixes. See
[`docs/releases/v1.0.1.md`](docs/releases/v1.0.1.md).

## [1.0.0] — 2026-06-16

First PyPI release of the Validity Warrant Protocol reference implementation.
