# Public real-repo micro-benchmark — results

> **Machine-derived structural-claim benchmark, reproducible on frozen SHAs.** Two public
> repositories were executed with **machine-derived** structural claims (operands extracted
> from source by `bench/public_claims.py`; `known_truth` observed by running the C3 checker on
> the mutated copy — no human semantic claim or truth label). Results are **reproducible on
> these frozen SHAs** only, with the **trigger and truth layers reported separately**. This is
> reproducibility evidence, not a real-world performance claim, and does not transfer to other
> repositories.

This is the results home for the `dorian bench public-repos` harness. It reports
**reproducibility evidence on frozen SHAs**, not a general claim about other repositories. The
two layers are kept apart: **trigger** = was the affected claim re-checked when its watched
source changed; **truth** = was it BROKEN / VERIFIED / ERRORED. `ERRORED` (a checker that could
not run) is its own bucket and is never an alarm. These repositories are **candidate benchmark
subjects**.

## Status

- Harness: **implemented** (`bench/public_repos.py`, wired as `dorian bench public-repos`).
- Claim synthesis: **implemented** (`bench/public_claims.py`) — deterministic, stdlib-only,
  emits a **proof object** per claim and promotes a `benchmark-ready` claim set only when every
  target validates (claim PASSes at the clean SHA; the mutation produces the declared verdict).
- Executed: **2 subjects** (`humanize`, `python-dotenv`), each run **twice**; the two runs are
  **byte-identical** (no timestamps in the output). The other subjects remain `NO_CLAIMS`.

## Executed results (machine-derived claims)

Run with `--deny-exec` (a fail-closed re-check policy, **not a sandbox**); all claims are C3
structural, so nothing is skipped. Each subject was run twice to a separate directory and the
JSON/JSONL compared byte-for-byte.

| repo | frozen SHA | license | status | trigger re-checked/skipped | truth broken/trusted/errored |
|---|---|---|---|---|---|
| `humanize` | `2ddb5903cdc1` | MIT | PASS | 4 / 0 | 3 / 1 / 0 |
| `python-dotenv` | `36004e0e34be` | BSD-3-Clause | PASS | 4 / 0 | 3 / 1 / 0 |
| `tomli` | `c5f44690c68c` | MIT | NO_CLAIMS | 0 / 0 | 0 / 0 / 0 |
| `bandit` | `92ae8b82fb42` | Apache-2.0 | NO_CLAIMS | 0 / 0 | 0 / 0 / 0 |
| `jaffle_shop_duckdb` | `36bde6cba69d` | Apache-2.0 | NO_CLAIMS | 0 / 0 | 0 / 0 / 0 |

- **Metrics (executed subjects):** claims_total = 8, mutations_total = 8, trigger
  selected/skipped = 8 / 0, truth BROKEN/TRUSTED/ERRORED = 6 / 2 / 0, match rate = 8/8.
  The sample (n=8) is far too small for a meaningful confidence interval — no CI is reported.
- **What `PASS` means here:** for each mutation the affected claim was re-checked (trigger) and
  its observed state equalled the machine-derived `known_truth` (truth). It does not mean the
  mechanism transfers beyond these frozen inputs.
- **TRUSTED controls** (1 per repo): a comment-only edit to `humanize.ordinal` and a
  docstring-only edit to `dotenv.set_key`. The claim is re-checked (the file changed) but the
  structural `py-signature` checker correctly stays PASS — the documented trigger-vs-truth
  ceiling: binding decides **when** to re-check, the checker decides **whether** a claim is false.

`sigstore-python` is **excluded** (`eligible: false`): GitHub's SPDX detector returns
`NOASSERTION`, so its license is unconfirmed — flagged, not silently swapped.

## Machine-derived claims (origins + proof)

Every executed claim is one of the allowed `generated-*` origins; broad natural-language
semantic claims are impossible from the generator (claim text is a fixed template over an
extracted fact). Per-claim proof objects (source file, extractor, locator, checker operand,
mutation id, observed `known_truth`) live in
`bench/public/repos/<repo>/claims.generated.json`.

| repo | claim | origin | known_truth |
|---|---|---|---|
| humanize | `naturalsize-signature` | generated-py-signature | BROKEN |
| humanize | `gnu-suffix-code` | generated-code-literal | BROKEN |
| humanize | `project-name-config` | generated-config-value | BROKEN |
| humanize | `ordinal-signature` (control) | generated-py-signature | TRUSTED |
| python-dotenv | `set-key-signature` | generated-py-signature | BROKEN |
| python-dotenv | `make-regex-signature` | generated-py-signature | BROKEN |
| python-dotenv | `single-quoted-key-code` | generated-code-literal | BROKEN |
| python-dotenv | `set-key-docstring-control` | generated-py-signature | TRUSTED |

**Rejected by design** (demonstrated in `tests/test_bench_public_claim_synthesis.py`, and the
reason the original drafts could not be promoted as-is): a `py-const` whose RHS is a
comprehension (`humanize.powers`) or a `Union[...]` subscript (`dotenv.StrPath`) is **not a
literal** — the generator rejects it (it would `ERROR`, not `BROKEN`), it is never forced into
the benchmark. `config-value` is generated only for TOML/JSON; a non-unique mutation `from` is
rejected.

## Reproduce

```bash
# 1. synthesize machine-derived claims from a frozen checkout (writes claims.json + proof)
uv run python bench/public_claims.py \
  --targets bench/public/repos/humanize/targets.json \
  --checkout <checkout-at-2ddb5903> --out-dir bench/public/repos/humanize

# 2. plan only — no clone, no seal, no results
dorian bench public-repos --manifest bench/public/manifest.v1.yaml --out bench/public/results --dry-run

# 3. run twice and compare for determinism (fail-closed re-check policy, not a sandbox)
dorian bench public-repos --manifest bench/public/manifest.v1.yaml --out bench/public/results/run1 --deny-exec
dorian bench public-repos --manifest bench/public/manifest.v1.yaml --out bench/public/results/run2 --deny-exec
diff -r bench/public/results/run1 bench/public/results/run2   # must be empty
```

## Allowed vs forbidden wording

Per [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md) and `PUBLIC_BENCHMARK_PROTOCOL.md` §8. The
report renderer (`render_report`) refuses the forbidden phrases mechanically.

- **Allowed:** "reproducible on these frozen SHAs", "candidate benchmark subjects", "trigger and
  truth layers reported separately", "reproducibility evidence, not a real-world performance claim".
- **Forbidden:** "validated on real repos", "works on real repos", "proves dorian works",
  "100% accurate", "generalizes", "production-grade" (and "proven", "universal", "guaranteed").
