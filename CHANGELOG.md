# Changelog

All notable changes to dorian (`dorian-vwp`) are recorded here. Full per-release notes live in
[`docs/releases/`](docs/releases/). The warrant format, checker grammar, exit codes, and trust
semantics have been stable since 1.0.0.

## [Unreleased]

## [1.3.0] — 2026-06-28

The **Dorian Claim Warrants for Claude Code** integration: one command scaffolds a project-local Claude
Code skill that drafts claim warrants for the checkable facts a coding agent says it changed, which
`dorian verify` then proves deterministically. **No breaking changes** — purely additive (a new CLI
subcommand, packaged templates, docs); warrant schema, checker grammar, exit codes, fold policy, and
security posture are unchanged, the core stays zero-dependency, and **no model is ever added to the
verification path**.

### Added
- **`dorian claude-code install-claim-warrants`** (`src/dorian/claude_code.py`) — scaffolds a
  project-local Claude Code skill at `.claude/skills/dorian-claim-warrants/` (invoked as
  **`/dorian-claim-warrants`**) that drafts `docs/changes/<slug>.md` + `docs/changes/<slug>.claims.json`
  for the *checkable* subset of a change summary (config values, signatures/defaults, constants,
  file/symbol references), then prints `dorian verify … --strength-gate=fail --binding-gate=warn`. The
  **model only drafts; Dorian verifies**. Writes files only (never runs a checker or executes code),
  stays inside the target repo, never overwrites without `--force`, and is idempotent. Flags:
  `--with-hook`, `--no-hook`, `--settings-only`, `--dry-run`, `--force`, `--print-next-steps`,
  `--target`.
- **Packaged skill templates** (`src/dorian/templates/claude_code/…`, shipped as wheel package data):
  `SKILL.md`, a bundle `README.md`, `examples/` (good/bad claims, a final-message walkthrough),
  `templates/` (change-note + claims.json skeletons), and `reference/` (checker-selection map,
  safety-boundary).
- **Opt-in, reminder-only Stop hook** (`hooks/dorian_claim_warrants_stop.py`, stdlib only). It returns a
  soft `additionalContext` nudge — **never a block**, so it cannot loop — and only when a turn left
  relevant, un-warranted code/config changes. It never runs `dorian verify` or tests, never writes
  files, and never executes project code (its only side effect is a read-only `git status`); it fails
  open. Not enabled by scaffolding — register it under `hooks.Stop` yourself.
- **Docs** — [`docs/DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md`](docs/DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md)
  (the integration guide) and [`docs/CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md`](docs/CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md)
  (how Dorian claim warrants differ from — and complement — the Agent Receipts action-audit protocol).

### Changed
- README, `docs/CLAUDE_CODE_DORIAN_WORKFLOW.md`, and `docs/POSITIONING_2026_06_27.md` adopt the
  **"claim warrants"** name (keeping "receipt" only as an explanatory metaphor, to avoid collision with
  the Agent Receipts project).

## [1.2.0] — 2026-06-27

C4 import-aware dependency binding, the opt-in truth-axis `--strength-gate`, and the
production-readiness / outside-world release docs. **No breaking changes** (the features are opt-in
or a re-check *trigger* widening only; warrant schema, checker grammar, exit codes, fold policy, and
security posture are unchanged; default behavior is identical).

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
- **Production-readiness & outside-world docs** — [`docs/PRODUCTION_READINESS_AUDIT.md`](docs/PRODUCTION_READINESS_AUDIT.md),
  [`docs/DORIAN_USEFULNESS.md`](docs/DORIAN_USEFULNESS.md), [`docs/READY_FOR_OUTSIDE_WORLD.md`](docs/READY_FOR_OUTSIDE_WORLD.md),
  and [`docs/OUTSIDE_WORLD_VALIDATION.md`](docs/OUTSIDE_WORLD_VALIDATION.md): an evidence-backed
  readiness review, the why-it-matters framing, the release-readiness verdict, and real external-repo
  validation trials (install-from-wheel on public projects, with drift/revocation).

### Changed
- The `bindings` / `--binding-gate` `trigger-only-symbol` diagnostic now treats a C4 test's
  import-derived watches as **checker-exercised** (the test imports and runs them), so widening a
  behavior claim's watch never spuriously flags it — and `--binding-gate=fail` does not start refusing
  good C4 behavior claims.
- **`--strength-gate off|warn|fail`** (on `seal` and `verify`; default `off`) — the **truth-axis**
  companion to `--binding-gate`. The protocol keeps two questions apart: binding gates *when* a claim
  re-checks (trigger), strength gates *whether* its checker can falsify it (truth). `strength.py`
  already classified checker strength and flagged adequacy mismatches, but only *printed* them
  (advisory); a load-bearing `behavior` claim backed only by an existence check therefore still sealed
  green — the review's named #1 false-confidence risk. `--strength-gate=warn` surfaces those
  diagnostics after a successful seal; `--strength-gate=fail` refuses the seal (writing nothing,
  exit 4, atomic no-write — mirroring `--binding-gate`) when a **load-bearing** claim is high-risk
  (`behavior` backed only by existence/raw-text/opaque-shell, `quantity` backed only by existence, or
  unbacked). It never marks a claim false and never touches trust/claim state; non-load-bearing claims
  and merely-`medium` risk never block; default `off` is byte-identical to prior behavior. The
  `strength` module stays out of the trust-state fold path (`fold.py`/`revalidate.py`); a regression
  test pins that invariant.
- **CI / release action pins bumped** (Dependabot #9–#13): `actions/checkout` v6.0.3,
  `actions/upload-artifact` v7.0.1, `actions/download-artifact` v8.0.1, `actions/cache` v5.0.5,
  `actions/attest-build-provenance` v4.1.0. These touch the release/publish/micro-benchmark workflows
  only — no runtime dependency, check-path, or default-behavior impact (core stays zero-dependency).

### Fixed
- **Truth-strength inversion in the adequacy lint.** A `behavior` claim backed *only* by an opaque
  C5 `shell:` checker (truth strength `shell_executable`, ranked *below* existence) received **no**
  `adequacy_mismatch`, because the behavior rule fired only on strengths in `_WEAK_FOR_BEHAVIOR`,
  which omitted `shell_executable` — so the weakest, un-introspectable backing silently passed a lint
  that a stronger existence backing tripped. `shell_executable` is now treated as too weak for
  `behavior` and `quantity` claims (it is opaque: dorian cannot see whether the command proves the
  claim), and the same fix lets a quantity claim backed only by an opaque shell be flagged. Advisory
  output only; no verdict, trust state, or exit code changes outside the new opt-in `--strength-gate`.
- **README quickstart claim kind.** The "Try it in 30 seconds" demo's existence claim
  (`handler() lives in app.py`, backed by a C3 `symbol:` existence check) was tagged `kind: behavior` —
  exactly the mismatch `--strength-gate=fail` refuses. Retagged `reference` so the headline demo is
  clean under the project's own truth-axis gate. Behavior-preserving under the default gate (off).

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
