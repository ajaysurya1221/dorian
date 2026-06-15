# V1 implementation tracker

Working tracker for the v0.11.0 → V1 strengthening program driven by
`RESEARCH_REPORT_DORIAN_0_11_0.md`. Behavior is verified against the **current
code**, not the report; where they disagree, code wins and the disagreement is
recorded here.

## Phase 0 — version gate + scope evidence

**Version gate: PASSED.**

| Surface | Observed |
|---|---|
| `pyproject.toml` `[project].version` | `0.11.0` |
| `src/dorian/__init__.py` `__version__` | `0.11.0` |
| branch | `main` |
| commit SHA (start) | `78dcd1a6a242110e55dc31fd1db2e811de3e3898` |
| working tree | clean except untracked `.claude/`, `AGENTS.md`, `CLAUDE.md`, `RESEARCH_REPORT_DORIAN_0_11_0.md` |
| Python | 3.12.4 |
| toolchain | `uv` 0.5.9; `uv run pytest`; ruff for lint/format |
| baseline tests | `uv run pytest -m "not slow"` → **561 passed, exit 0**; 636 total incl. slow |

## Phase 1 — baseline reconstruction (from current code)

### Module map
- `model.py` — `Warrant`/`Claim`/`CheckerSpec`/`ReadSetEntry`, content-addressed id, canonical JSON. `CheckerType = C1|C3|C4|C5` (a *Literal* hint; registry dispatch is on the string `type`).
- `checkers/base.py` — `run_checker` is the single dispatch + the single execution-policy gate (blocked → `Verdict.ERROR`).
- `checkers/c1_span.py` — span anchor, relocation-tolerant, optional c2lite.
- `checkers/c3_ref.py` — `path:` / `symbol:` / `string:` / `regex:`; regex match in a spawn-killed worker (ReDoS backstop).
- `checkers/c4_test.py` — `pytest:<nodeid>`, careful exit-code mapping; ERROR≠FAIL.
- `checkers/c5_data.py` — typed data forms + opaque `shell:`.
- `policy.py` — `ExecutionPolicy`, `executable_kind` (single source of "what executes": C4=pytest, C5 shell=shell).
- `seal.py` — born-verifiable seal; scope lint; watch derivation; additive symbol-definer widening; duplicate-id reject; atomic write; idempotent re-seal.
- `revalidate.py` — changed-path discovery, rename persistence, cheapest-first checks (C1<C3<C5<C4), fold, recall fanout; ERROR→ERRORED.
- `fold.py` — `fold()` pure fn → TRUSTED/DEGRADED/REVOKED/UNKNOWN. (Born state is `WARRANTED`, set at seal.)
- `bindings.py` — binding diagnostics + opt-in `--binding-gate` (off/warn/fail). Flags: unbacked, single-file, short-literal, ambiguous-mention, trigger-only-symbol, unwatched-mention.
- `symbol_index.py` — Python symbol→definer index + pyproject console-script index; ambiguity skipped.
- `gitio.py` — git plumbing incl. `file_at_ref` (needed for trusted-base).
- `commands.py` / `cli.py` — command surface; exit codes 0/2/3/4/5/6.
- `store.py` / `blast.py` / `report.py` — derived SQLite, lineage, audit JSONL.

### Trust-boundary map
- Non-executable: C1, C3, typed C5. Executable: C4 `pytest:`, C5 `shell:`.
- `--deny-exec`/`--deny-shell` (+ env) are fail-closed, NOT a sandbox. Blocked → ERROR.
- Sidecars are source of truth; SQLite derived (`sync` rebuilds).
- Action runs checkers from the **checked-out (head)** sidecars → trusted/internal only today; trusted-base is design-only (`docs/TRUSTED_BASE_ACTION_DESIGN.md`).

### Benchmark/docs freshness map
- `docs/BENCHMARK_v0.7.0.md` — title-stamped **v0.7.0**, synthetic. HISTORICAL.
- `docs/BENCHMARK_BINDING_LIFECYCLE.md` — header `dorian 0.9.0`, run_id, 808 pairs. HISTORICAL.
- `docs/PUBLIC_BENCHMARK_PROTOCOL.md` — protocol only, no results.
- No current-version (0.11+) result doc exists.

### Report findings verified against code (code wins)
- **README `WARRANTED -> REVOKED` is NOT drift.** Report (medium-confidence) called it stale. Verified: `fold.fold()` only emits TRUSTED/DEGRADED/REVOKED/UNKNOWN; the *born* trust state is `WARRANTED` (set at seal); the first fold therefore renders `WARRANTED -> <new>`. `tests/test_render_md.py:168-169` pins `WARRANTED -> REVOKED` and `WARRANTED -> UNKNOWN` as correct md output. Action: **do not "fix"; add a short trust-state vocabulary note to remove reader confusion.**
- **C4 adequacy blind spot** — report marks INFERENCE; confirmed: `c4_test.py` maps pytest exit codes only, no assertion/relevance inspection. Valid advisory target (WP6).
- **PyPI install wording** — report marks UNVERIFIED. Per project state, dorian is NOT on PyPI; README "until the first PyPI release … install from source" is accurate. Keep.

## Report coverage matrix (every material finding classified)

Categories: IMPL=must-implement · TEST=must-test regression · DOC=must-document · BENCH=must-benchmark · BOUNDARY=honest non-goal · DONE=already in v0.11.0 · DEFER=post-V1/blocked.

| # | Report finding / recommendation | Category | Current evidence | Planned action | Acceptance/verification | Status |
|---|---|---|---|---|---|---|
| 1 | README trust-state vocab (WARRANTED vs TRUSTED/…) | DOC | code correct; README lacks a glossary | add trust-state legend; keep examples | docs test + render_md tests stay green | TODO |
| 2 | ERROR must never collapse into BROKEN | DONE+TEST | base/fold/revalidate all enforce | keep; add a guard test if any new path | existing + new ERROR≠BROKEN tests | TODO |
| 3 | C1 span + c2lite regression | DONE | test_c1.py | none (keep green) | test_c1 passes | DONE |
| 4 | C3 regex ReDoS timeout regression | DONE | test_c3_regex_timeout.py (slow) | none | passes | DONE |
| 5 | C3 symbol existence ceiling / gutted-body | IMPL+DOC | symbol: existence-only | add `py-signature:` structural checker (WP3) | gutted-body PASS under symbol, FAIL under signature when sig changes; body-only stays PASS (documented ceiling) | TODO |
| 6 | C3 string/regex comment/docstring survival | IMPL+DOC | raw text search | add semantic code-context search mode (WP4) | literal only in comment/docstring → FAIL in code mode | TODO |
| 7 | C4 pytest vacuous/zero-assertion adequacy | IMPL | none | advisory adequacy lint (WP6) | zero-assertion / assert-True node warns; normal test does not | TODO |
| 8 | C5 typed grammar limits / snapshot brittleness | BOUNDARY+DOC | documented | document in V1-meaning; optional structural data checker DEFER | doc states grammar bounds | TODO |
| 9 | duplicate claim-id rejection | DONE | seal.py step 0 | keep | test_seal covers | DONE |
| 10 | scope-lint named-read-set-only limitation | DONE+DOC | SECURITY_BOUNDARY | keep wording | docs test | DONE |
| 11 | deny-exec/deny-shell fail-closed, not sandbox | DONE | policy.py, docs | keep | test_deny_exec_policy | DONE |
| 12 | sidecar source-of-truth vs SQLite derived | DONE | seal/revalidate/sync | keep | test_store/sync | DONE |
| 13 | canonical JSON / content-addressed identity | DONE | model.compute_id + Warrant.load integrity | keep | test_model/determinism | DONE |
| 14 | atomic no-write on failed seal | DONE | seal os.replace + refusal order | keep | test_seal/deny_exec | DONE |
| 15 | changed-path discovery + persisted rename | DONE | revalidate + store rename_log | keep | test_revalidate | DONE |
| 16 | checker ordering + FAIL vs ERROR discipline | DONE | revalidate _check_claim | keep | existing | DONE |
| 17 | fold + blast/recall lineage | DONE | fold.py, blast.py | keep | test_fold/test_blast | DONE |
| 18 | audit/state separate-transaction limitation | BOUNDARY | fold.py docstring documents it | document in V1-meaning as known limitation | doc names it | TODO |
| 19 | binding ambiguity handling | DONE | symbol_index ambiguous_symbol_mentions + flag | keep; extend provenance (WP5) | test_symbol_index | DONE |
| 20 | oversized/unparseable file diagnostics | IMPL | silently skipped today | surface multi-index unparse diagnostics (WP5) loudly | giant/unparseable supported file → diagnostic not silent | TODO |
| 21 | pyproject script binding | DONE | pyproject_script_definers | keep | test_symbol_index | DONE |
| 22 | watch glob over/under-match risk | TEST | _covered glob logic | add a glob over/under test if WP5 touches it | test | TODO |
| 23 | public/fork self-attested verdict risk | IMPL+DOC | head-mode only | trusted-base checker-source (WP7) | exploit fixtures: PR-added/modified exec checker not run; non-exec rewrite surfaced | TODO |
| 24 | trusted-base design + non-sandbox caveat | IMPL+DOC | design-only | implement `--checker-source base` + Action input; keep non-sandbox caveat | WP7 test matrix | TODO |
| 25 | historical benchmark docs (v0.7.0, v0.9.0) | DOC | unlabeled as historical in body | add HISTORICAL banner; README cross-link labels | docs wording test | TODO |
| 26 | public benchmark protocol w/o results | DOC | protocol only | keep; note in current-results doc | unchanged | TODO |
| 27 | current-version benchmark rerun | BENCH | none | rerun + version-stamped `BENCHMARK_CURRENT.md` | bench smoke + stamp present | TODO |
| 28 | extractor remains draft/experimental | DONE | README + AGENT_CLAIMS | keep; do not promote | docs test | DONE |
| 29 | release/install-status uncertainty | DOC | README source-install accurate | keep; V1 release report states status | report | TODO |
| 30 | checker-strength / claim-risk visibility | IMPL | bindings flags exist but no strength score | strength + claim-risk diagnostics (WP2) | behavior+symbol → adequacy-mismatch; unbacked load-bearing → high risk | TODO |
| 31 | multi-index binding (routes/config/etc.) | IMPL | python+script only | config-key index (WP5), provenance-tagged | config-key change selects claim; ambiguous skipped+warned | TODO |
| 32 | warrant-quality mutation harness | BENCH | repo-level bench only | `dorian bench warrant-quality` (WP8) | deterministic per-claim trigger/truth score on fixture | TODO |

## Work-package status (live)

| WP | Title | Status |
|---|---|---|
| WP1 | docs/evidence hygiene | DONE (trust-state legend; historical banners on v0.7.0/0.9.0 benchmark docs; docs/V1_SCOPE.md; README command-surface + new-forms + historical labels; benchmark-evidence wording tests) |
| WP2 | checker-strength / claim-risk linter | DONE (strength.py; surfaced in `bindings` + binding-gate warn; 19 tests) |
| WP3 | Python structural checkers (py-signature, py-const) | DONE (pyast.py + C3 subgrammars; 27 tests incl. e2e) |
| WP4 | semantic-context source search (`code:`) | DONE (pyast.code_only_python + C3 `code:`; 12 tests) |
| WP5 | multi-index binding (config-key) | DONE (symbol_index.config_key_index + claim_watch_paths; TOML/JSON only, YAML excluded = zero-dep; provenance in bind-suggest; ambiguity + unparseable surfaced; 9 tests) |
| WP6 | C4 test-adequacy lint | DONE (strength.c4_adequacy; folded into WP2 tests) |
| WP7 | trusted-base checker-source mode | DONE (revalidate --checker-source base + Action checker_trust; 10-case exploit matrix) |
| WP8 | warrant-quality mutation harness | DONE (bench/warrant_quality.py; `dorian bench warrant-quality`; deterministic, offline, never mutates real repo; trigger vs verdict; ERROR bucket distinct; honest scope = structural/existence forms scored, others reported strength-only; 7 tests) |
| WP9 | current-version benchmark results | TODO |
| WP10 | V1 release prep / decision | DONE — version surfaces synced to `1.0.0rc1` (pyproject/__init__/uv.lock); no tag/push/publish. All gates pass; adversarial-review BLOCK resolved. |

Branch `dorian-v1-strengthening`, 9 commits off `main`:
`58b39e2` WP3/4/2/6 · `6a8298c` WP7 · `04ab60b` WP5 · `2a66a49` WP8 · `4e586a7` WP9/WP1 ·
`2a4befa` byte-match fix · `a6595ba` adversarial-review BLOCK fixes · `b7376e7` bump 1.0.0rc1 ·
`4710604` benchmark re-stamp.

Adversarial review (5 lenses, BLOCK): 6 must-fixes + 2 hygiene items all resolved with
regression tests. Final gate: ruff clean, 658 non-slow pass, 733 total (incl slow) green.
