# dorian v0.3.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

v0.3.0 is a **benchmark-phase release**: no functional code changes since
v0.2.0. It publishes the multi-run extraction-churn benchmark.

## What's new since v0.2.0

- **`docs/CHURN_BENCHMARK_v0.3.0.md`** — seven isolated benchmark runs
  independently ran the extraction-churn benchmark (21 fresh temperature-0
  extraction runs on a hash-pinned, sanitized copy of the public demo doc;
  every reported number recomputed from raw artifacts; 7/7 valid runs, none
  excluded). Headline: exact churn mean **0.187 ± 0.032 (SEM)**, range
  0.074–0.290, with only 3/7 invocations clearing the 0.20 advisory gate —
  the gate verdict itself is unstable run-to-run. Fuzzy churn is near zero
  (0.016) with stable claim counts (17–18), so the instability is mostly
  claim *wording*, not claim *selection*, on this document.
- Consequence, stated plainly: `--extract` remains **experimental and
  draft-only**. This release adds the variance evidence behind that status;
  it does not change it.
- Version and pin examples updated to the 0.3 series.

## What works now

Unchanged from v0.2.0: the full local loop (`capture` → `seal` →
`revalidate` → `status` / `report --audit` / `blast`), C1/C3/C4/C5 checker
families, trust-state folding with audit export and downstream recall,
content-free sidecar mode, scope lint, and the composite GitHub Action
(trusted/internal repositories recommended — see `action/README.md`
security notes).

## How to try it

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'
```

Follow the 60-second example in the README. The deterministic selftest
benchmark runs with `make bench`; the full test suite with `make test`;
measure extraction churn on your own documents with `dorian bench churn`.

## Caveats

Unchanged from v0.2.0 (see `docs/RELEASE_NOTES_v0.2.0.md` and
`docs/RELEASE_VALIDATION_REPORT_v0.2.0.md`): R&D stage; the headline
benchmark result (32.40× / 0.89 recall) is a research-preview figure on
private repositories, not independent public proof; Action security caveats
apply; `--extract` is experimental and draft-only — now with multi-run
variance data to show why.

## Next steps

- Level 1 of `docs/SOLO_VALIDATION_LADDER.md`: the reproducible public
  micro-benchmark.
- Extraction-prompt hardening and anchor-first extraction
  (`docs/NEXT_ALGORITHMIC_BETS.md`) — the documented path to a stable
  extractor.
- First PyPI release of `dorian-vwp`.
