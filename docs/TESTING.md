# Testing & the quality gate

dorian's behavior is exercised by a layered pytest suite. This is the
solo-maintainer's guide: what to run before committing, what each layer proves,
and how to run the heavier release checks.

## The one command

Before any commit or release:

```bash
make test        # the full gate: every test, incl. benchmarks + a real wheel build/install
```

`make test` runs `uv run pytest` — unit, integration, CLI black-box, edge/error,
security, determinism, performance, the benchmark determinism/regression pins, and
the packaging (wheel build → fresh-venv install → console-script) gate. This is the
release gate. CI runs it on Python 3.11 / 3.12 / 3.13.

## Fast iteration gate

```bash
make test-fast   # uv run pytest -m "not slow"
```

Use this for rapid edit/test loops. It drops the heaviest ~minute of the suite (the
controlled-/large-mutation benchmark runs, the wheel build, and the C4
real-`pytest`-subprocess checks). **Always run the full `make test` before commit** —
the fast gate intentionally omits the benchmark regression pins and the packaging gate.

## Lint / format / coverage

```bash
make lint        # ruff check + format --check on src/ tests/ bench/
make fmt         # auto-fix + format
make coverage    # coverage (term-missing + HTML under htmlcov/), measured over the dorian package
```

## What each layer proves

| layer | file(s) | proves |
|---|---|---|
| kernel lifecycle | `test_e2e.py` | capture → seal → revalidate → fold on the fixture repo |
| checkers | `test_c1/c3/c4/c5.py` | each checker's verdict matrix (PASS / FAIL / ERROR) |
| pipeline + index | `test_seal/store/fold/blast/bindings.py` | warrant sealing, the derived SQLite index, trust fold, blast radius |
| agent-claims contract | `test_claims_io.py`, `test_verify.py` | the `claims.json` contract + `dorian verify` |
| **CLI black-box** | `test_cli_blackbox.py` | the real entry point out-of-process (`python -m dorian`): help/version, every subcommand, exit codes, a full lifecycle |
| **edge / error** | `test_cli_edge_cases.py` | malformed / empty / large / unicode / out-of-repo inputs → correct exit code, prefixed error, no sidecar, no traceback |
| **security** | `test_security.py` | path-traversal blocked (no out-of-repo read), ReDoS length cap, checker env-stripping, audit detail redaction |
| **determinism / flake** | `test_determinism.py` | id is a pure function of the body; `report --audit` byte-identical; `sync` idempotent; `revalidate` stable across repeats |
| **performance** | `test_perf_smoke.py` | coarse latency budgets (gross-regression / hang guards, not microbenchmarks) |
| **packaging (release gate)** | `test_packaging.py` *(slow)* | a built wheel installs into a clean venv and the `dorian` console script runs end-to-end |
| benchmarks *(slow)* | `test_controlled_mutation.py`, `test_large_mutation.py` | benchmark determinism + the pre-registered confusion-matrix regression pins |

## Environment

- **Zero runtime dependencies** — the core install needs only Python ≥ 3.11.
- Optional extras: `[data]` (duckdb, for parquet C5 data claims), `[extract]`
  (anthropic, for the **frozen** LLM claim drafter). CI uses `uv sync --all-extras`.
- `DORIAN_EXTRACT_STUB=<claims.json>` makes the extractor offline-deterministic (used
  by the extraction tests); no API key is needed to run the suite.
- No credentials, services, or network are required. The packaging test builds
  offline (zero deps) and skips cleanly if `uv` is unavailable.

## Known residual risks

- **ReDoS:** C3 regex runs in-process with a 500-char pattern cap but no runtime
  timeout; catastrophic backtracking *within* the cap is a documented residual risk.
  `docs/AGENT_CLAIMS.md` steers authors toward literal-anchored patterns; review
  agent-emitted regex claims.
- **Re-seal idempotency (resolved):** re-running `verify`/`seal` on a *materially
  identical* artifact keeps the committed sidecar byte-for-byte — the two per-run
  wall-clock stamps (`sealed_at`, `produced_by.captured_at`) are masked when comparing
  to the existing sidecar, so a re-run no longer churns a committed sidecar. Any real
  change re-seals; `seal --supersede <old-id>` records an intentional supersession.
  Pinned by `tests/test_determinism.py::test_reseal_of_identical_content_is_idempotent`.
- **CI is Ubuntu-only:** path / subprocess behavior on macOS and Windows is not yet
  gated in CI (the suite passes locally on macOS).
- **Local subprocess tests can flake in sandboxed / worktree environments:** the
  out-of-process tests (`python -m dorian` black-box, packaging, C4 real-`pytest`
  spawns) need a working editable install on `PATH`; under endpoint-security scanning
  or an unstable worktree editable install they can stall or `ModuleNotFoundError`
  even when the code is correct. Confirm logic with the focused in-process tests
  (`PYTHONPATH=src uv run --no-sync pytest <files>`), and treat **CI
  (`uv sync --all-extras` on 3.11 / 3.12 / 3.13) as authoritative** for the full
  suite. Do not work around the stall by changing the C4 PATH-interpreter contract,
  and do not report a green run that did not happen.
