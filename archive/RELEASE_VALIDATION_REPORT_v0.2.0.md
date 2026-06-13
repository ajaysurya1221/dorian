# Release validation report — v0.2.0 (2026-06-12)

> **ARCHIVED / SUPERSEDED — HISTORICAL RECORD, NOT CURRENT EVIDENCE.** Retained as
> development history only. The current public benchmark is the controlled-mutation
> benchmark with known-truth labels (`docs/BENCHMARK_v0.6.0.md`); the README cites
> nothing in this file.

Evidence record for the v0.2.0 public R&D preview. Four independent review
passes were run with fresh context against the release tree: benchmark-claim
audit, functionality/end-to-end, privacy/security, and prior-art boundary.
The reviews were performed by AI review panels executing real commands; no
independent human review is claimed. Everything below is reproducible from
the commands shown, and contains aggregate numbers only.

## Verdict table

| Gate | Verdict | Blockers |
|---|---|---|
| Benchmark and claim-number audit | PASS | none |
| Functionality and protocol (incl. E2E) | PASS | none |
| Security, privacy, release safety | PASS | none |
| Prior-art / no-wheel-reinvention | PASS (no collision) | none |

## 1. Benchmark-claim audit

The README's benchmark paragraph was audited number by number. Every figure
was **recomputed from the local benchmark artifacts using the repo's own
aggregate-only commands** (`python -m bench.owner_review owner-metrics`,
`dorian bench public-summary`) — no document was taken at its word. Raw
benchmark artifacts are local-only and were not opened beyond aggregate
counts; nothing private appears here.

| Claimed | Recomputed | Match |
|---|---|---|
| 32.40× false-positive reduction | 32.40 (162 baseline FPs ÷ 5 dorian FPs; 95% CI 17.00–157.00) | yes |
| 0.89 recall | 0.8889 (8 of 9 owner-checked true staleness events; CI 0.67–1.00) | yes |
| 556 artifact-commit pairs | 556, rederived independently from the window composition (40×1 + 6×6 + 60×4 + 60×4) | yes |
| three repositories | 4 benchmark windows over 3 distinct repositories | yes |
| 72-pair spot-check | 72/72 rows labeled, 2 overrides, 0 unsure, 0 out-of-scope | yes |
| recommendation PASS | PASS, recomputed live by `owner-metrics` | yes |
| churn exact 0.49 / fuzzy 0.21 vs < 0.20 gate | exact mean 0.4923 (runs 0.585/0.524/0.368), fuzzy mean 0.2054, gate fail | yes |

Fresh recomputations were byte-identical to the stored summary files — the
published numbers have not drifted from the artifacts that produced them.
Label provenance: blind model-panel labels (201/201 unanimous pairs judged)
with an owner spot-check of 72 pairs producing 2 overrides; the README's
wording ("model-adjudicated with a human spot-check, not fully
human-labeled") matches the evidence and the superseded earlier panel-only
figures remain quotable only behind the supersession notice in
[`KILL_REPORT_v0.0.md`](KILL_REPORT_v0.0.md).

## 2. Local functionality suite

```text
uv run ruff check .                        -> All checks passed!
uv run ruff format --check src tests bench -> 55 files already formatted
uv run pytest                              -> 410 passed
uv run dorian --help                       -> exit 0 (all 10 subcommands)
uv run dorian bench --help                 -> exit 0 (5 bench subcommands)
```

## 3. Clean-archive validation

`git archive HEAD` extracted to a scratch directory, then `uv sync
--all-extras`, `dorian --help`, and the full test suite: **410/410 passed**
from the archive tree. The archive contains
`examples/demo-repo/docs/design.md` (the committed public demo fixture) and
none of the local-only directories.

## 4. End-to-end workflow proof

Run in a disposable temp git repo built from the committed demo fixture, with
`ANTHROPIC_API_KEY` stripped from the environment for every command (zero
model tokens by construction):

| Step | Evidence |
|---|---|
| Capture read-set from manual specs | `captured 2 read-set entries (coverage 1.00)` |
| Seal runs every checker, writes sidecar | warrant id emitted; sidecar present |
| Negative seal: failing checker refuses to seal | `FAILED_AT_SEAL`, exit 4, no sidecar written |
| Unrelated commit | `checked 0 candidate claim(s)`, exit 0 |
| Breaking change (timeout 30→10) | exactly `c-02 BROKEN`, fold `WARRANTED -> REVOKED`, exit 4 |
| Downstream recall | `recalled docs/rollout-plan.md depth=1`; downstream states untouched |
| `status` | `REVOKED docs/design.md BROKEN=1 VERIFIED=1`, exit 4 |
| `report --audit` | `dorian-audit-v1` JSONL, byte-identical across two runs |
| `blast` | downstream artifact listed at depth 1 via the broken warrant |
| Heal path | re-fix folds `REVOKED -> TRUSTED`, exit 0 |
| Exit-code contract | 0/2/3/4/6 each demonstrated live (5 covered by the test suite) |

Docs-vs-reality: every command, flag, and behavior named in the README
"Command surface" section and `action/README.md` was checked against
`--help` output, `action/action.yml`, and live runs; no discrepancies.

## 5. Extraction smoke test (advisory)

With a live API key, `dorian bench churn` ran 3 extraction re-runs on the
committed public demo doc: the API path works; churn failed its stability
gate (`exact=0.222` vs `< 0.20`). This is the documented expected behavior —
`--extract` is experimental and draft-only, and this result is why.

## 6. Privacy and release-safety scans

- `bench/real/` not tracked; no owner-review/panel/labeling data files
  tracked (matches are public process docs only).
- Forbidden-string sweeps (private names, internal hosts, `/Users/` paths,
  token shapes, email addresses) over the tracked tree, the lockfile
  (non-hash lines), the banner PNGs (`strings`), and the sanitized export
  tree: all clean. The only identity anywhere in public history is the
  GitHub noreply address.
- `.gitignore` covers `.env`, `bench/real/`, and the local index; the
  public remote contains exactly `main` and the `v0.1.0` tag.

## 7. GitHub Action security posture

The Action's trust boundary is documented in
[`action/README.md`](../action/README.md): checker specs in `.warrant`
files are executable, so the Action is recommended for trusted/internal
repositories until a trusted-base mode exists; `pull_request` only, no
secrets in untrusted jobs; infra failures (exits 2/5) fail loudly and are
never reported as stale claims. The YAML matches the documented claims:
inputs flow via `env` (not inline interpolation), PR-controlled log output
is fenced against workflow commands, and the sticky-comment lookup filters
by bot author.

## 8. Prior-art boundary

A targeted sweep (2026-06-12) of Agent Receipts, the Microsoft Agent
Governance Toolkit, Swimm/DeepDocs/Dosu/driftdev.sh, SLSA/in-toto,
OpenLineage/DataHub, Great Expectations, Pact/PactFlow, LangSmith/OpenAI
Agents tracing, MCP receipt systems, and fiberplane/drift found **no system
combining** read-set capture + atomic claims + executable claim-level
checkers + zero-token revalidation + trust-state lifecycle + downstream
recall in a git-native sidecar workflow. Agent receipt and governance
systems cover agent *actions*; `dorian` warrants generated artifacts after
they exist. Standing watchlist: [`NAMING_AND_PRIOR_ART.md`](NAMING_AND_PRIOR_ART.md).
