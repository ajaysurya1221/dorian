# V1 alignment report

Final report for the v0.11.0 → V1 strengthening program driven by
`RESEARCH_REPORT_DORIAN_0_11_0.md`. Every completion claim below is backed by a file
path and a command/test result. Behavior was verified against the current code; where
the report and code disagreed, code won (recorded in `V1_IMPLEMENTATION_TRACKER.md`).

## 1. Version gate result

| surface | start | final |
|---|---|---|
| `pyproject.toml` `[project].version` | `0.11.0` | `1.0.0rc1` |
| `src/dorian/__init__.py` `__version__` | `0.11.0` | `1.0.0rc1` |
| `dorian --version` | `dorian 0.11.0` | `dorian 1.0.0rc1` |
| branch | `main` @ `78dcd1a` | `dorian-v1-strengthening` @ `4710604` |

Version gate **PASSED** at start (both surfaces `0.11.0`). No tag, push, publish, or
remote change performed.

## 2. Executive result

**V1 release candidate ready** (`1.0.0rc1`). All ten work packages are implemented (or
explicitly deferred with reasons), tested, and documented; a 5-lens adversarial review
returned BLOCK and all six must-fix findings are resolved with regression tests; the full
733-test suite and lint pass at the release commit.

## 3. Work completed

| WP | Status | Files | Tests | Caveat |
|---|---|---|---|---|
| WP1 docs/evidence hygiene | complete | README, docs/V1_SCOPE.md, BENCHMARK_v0.7.0/BINDING_LIFECYCLE banners, BENCHMARK_CURRENT.md | test_benchmark_evidence (5) | trust-state legend + historical labels |
| WP2 checker-strength / claim-risk | complete | src/dorian/strength.py, commands.py (bindings + binding-gate) | test_strength (20) | advisory only; never changes verdict/exit |
| WP3 Python structural checkers | complete | src/dorian/pyast.py, checkers/c3_ref.py, seal.py, spec/checkers.md | test_pystructural (29) | gutted-body is the documented ceiling |
| WP4 semantic-context `code:` | complete | pyast.code_only_python, c3_ref.py | test_semantic_context (14) | Python-only (documented) |
| WP5 multi-index binding (config-key) | complete | symbol_index.py (config_key_index, claim_watch_paths), commands.py | test_config_binding (12) | TOML/JSON only; YAML excluded (zero-dep) |
| WP6 C4 test-adequacy lint | complete | strength.c4_adequacy | (in test_strength) | advisory; conservative on helpers |
| WP7 trusted-base checker-source | complete | revalidate.py, cli.py, commands.py, action/action.yml | test_trusted_base (10) | trust root, NOT a sandbox |
| WP8 warrant-quality harness | complete | bench/warrant_quality.py, commands.py | test_warrant_quality (7) | structural/existence forms scored; others strength-only |
| WP9 current-version benchmarks | complete | docs/BENCHMARK_CURRENT.md | docs wording tests | synthetic-suite reproducibility only |
| WP10 release prep | complete | pyproject/__init__/uv.lock → 1.0.0rc1 | test_version_sync (3) | rc, not final 1.0.0 |

**Deferred (classified in `docs/V1_SCOPE.md`, not V1 blockers):** declarative-structural
checkers (config/OpenAPI/SQL value/type — the report's C7-style family), route/SQL binding
indices, YAML config binding (needs a runtime dep), the real-repo public micro-benchmark
(protocol exists; results post-V1), and audit-event/state single-transaction atomicity
(pre-existing, documented in `fold.py`).

## 4. Commands run (final state, commit `4710604`)

| command | result |
|---|---|
| `uv run dorian --version` | `dorian 1.0.0rc1` |
| `uv run ruff check src tests bench` | `All checks passed!` |
| `uv run ruff format --check src tests bench` | `108 files already formatted` |
| `uv run pytest -m "not slow"` | exit 0 — **658 passed** |
| `uv run pytest -m slow` | exit 0 — slow suite passed (wheel build, real pytest subprocess, regex-timeout) |
| `uv run pytest` (full, incl slow) | exit 0 — **733 collected** (baseline 636 → +97) |
| `dorian bench large-mutation` | 240 pairs, P=R=0.93, 11.6×/10.4× FP reduction |
| `dorian bench binding-lifecycle` | 808 pairs, selection recall 0.54→1.00, alarm precision/recall 1.00, 0 errored |
| `dorian bench realworld-usecases` | 5 cases: 2 solved / 1 partial / 2 not_solved |
| `mcp gitnexus detect_changes` (pre-commit) | changed symbols == intended; no surprise blast radius |

## 5. Verification evidence

- **Test suite:** 733 tests pass at `4710604` (lint + non-slow + slow all exit 0). +97 over
  the 636-test `78dcd1a` baseline, across 6 new test files
  (test_pystructural, test_semantic_context, test_strength, test_trusted_base,
  test_config_binding, test_warrant_quality, test_benchmark_evidence).
- **CLI smoke:** `dorian bindings <artifact>` shows strength/risk (JSON + human golden tests);
  `dorian bench warrant-quality --json` emits `dorian-warrant-quality-v1`;
  `dorian revalidate --checker-source base` and env `DORIAN_CHECKER_SOURCE` both exercised.
- **Security fixtures:** `tests/test_trusted_base.py` (10) proves each "executed?" case with a
  sentinel `touch` that must NOT appear under base mode — PR-added and PR-modified executable
  checkers never run; missing/tampered base sidecar fails closed (ERRORED); deny-exec composes.
- **Benchmarks:** re-run at `1.0.0rc1`; figures identical to the historical runs (large-mutation
  vs v0.7.0; binding-lifecycle same content-derived run_id as 0.9.0) — additive, no regression.
- **Docs wording:** historical docs carry version stamps/banners; `BENCHMARK_CURRENT.md` is
  version+commit stamped with a what-it-does-NOT-prove block; guard tests pin all of it.

## 6. Trigger-vs-truth preservation

The distinction is preserved and made **more visible**, never blurred:

- **Binding (trigger) stays trigger-only.** Config-key binding (WP5) and symbol binding only
  widen the re-check set; `docs/VALIDATION_HONESTY.md`, `docs/V1_SCOPE.md`, and the
  binding-lifecycle benchmark all state a watched-file change never makes a claim BROKEN by itself.
- **New truth-axis surfacing.** WP2 checker-strength classifies each checker's falsifying power
  and flags kind-vs-strength **adequacy mismatches** (a `behavior` claim backed only by an
  existence/text checker; a vacuous pytest node). WP8 warrant-quality scores per-claim
  caught/missed/brittle/**ceiling** offline.
- **The ceiling is pinned, not hidden.** `py-signature:`/`symbol:` on a gutted-body change PASS
  (a `test_..._gutted_body_still_passes_documented_ceiling` test asserts it); only a C4 test
  catches a body change. ERROR is never BROKEN — a new end-to-end test drives a new-form ERROR
  and asserts it lands in `errored` (exit 5), never `broken`.

## 7. Security posture

- **Trusted/internal (`head`, default):** unchanged from v0.11.0 — executes the checked-out
  checker specs. Correct where everyone who can open a PR is trusted to run code in CI.
- **Public/fork (`checker_trust: base`):** **implemented and tested** (WP7). Resolves each
  claim's checker spec from the base ref, so PR-added/modified executable checkers never run and
  a rewritten checker cannot self-attest a verdict; fails closed on a missing/tampered base
  sidecar. The `SECURITY.md` / `action/README.md` contradictions (which still said it was
  unimplemented) were fixed and a guard test prevents recurrence.
- **Remaining non-sandbox caveat (stated everywhere):** a base-approved `pytest:` checker can
  still execute PR-head code. base mode is a **checker-source trust root, not a sandbox** — for
  fully untrusted forks combine `checker_trust: base` with `deny_exec: true` (or external
  isolation). `--deny-exec`/`--deny-shell` remain fail-closed, not sandboxes.

## 8. Benchmark / evidence posture

- **Current results:** `docs/BENCHMARK_CURRENT.md` — version+commit stamped (1.0.0rc1 / `b7376e7`),
  reproduction commands, environment, and an explicit non-overclaim block.
- **Historical docs labeled:** `BENCHMARK_v0.7.0.md` (version-stamped title; it is byte-matched to
  its generator so it cannot carry a hand banner) and `BENCHMARK_BINDING_LIFECYCLE.md` (0.9.0,
  HISTORICAL banner). Both preserved verbatim and cross-referenced from the current doc.
- **What the benchmarks support:** reproducibility on the named synthetic suites at the stamped
  version, fewer false re-checks than file watchers, near-complete binding trigger recall with
  zero false BROKEN — and that V1's additions did not regress any of it. **Not supported:**
  "works on real repos", "validated", or that binding proves behavior (the gutted-body ceiling).

## 9. Remaining risks and non-goals (after implementation)

- **No real-repo validation yet** — evidence is synthetic-suite reproducibility plus offline
  public-case reproductions; the public frozen-SHA micro-benchmark is protocol-only (post-V1).
- **`code:`/structural forms are Python-only**; other languages keep the raw-text survival class.
- **Config binding is TOML/JSON only** (YAML needs a runtime dep); unparseable supported config
  files are surfaced, not silently skipped.
- **Audit-event/state atomicity** — change + event still commit separately (`fold.py`); a crash
  between them can drop the event. Pre-existing, documented.
- **`--extract` stays draft/experimental** — not promoted in V1.

## 10. Release decision

**V1 release candidate prepared.** All quality gates passed, so version surfaces were synced to
`1.0.0rc1` (pyproject / `__init__` / uv.lock; `dorian --version` agrees; `test_version_sync`
green). It is a **release candidate, not final 1.0.0** — honest given the deferred post-V1 items
above and the absence of real-repo validation. **No tag, push, publish, or remote/secret change
was performed**, per the operating rules; the work lives on branch `dorian-v1-strengthening`
(9 commits off `main`). Suggested next steps (owner's call): open a PR to `main`, then run the
real-repo public micro-benchmark before promoting `1.0.0rc1 → 1.0.0`.
