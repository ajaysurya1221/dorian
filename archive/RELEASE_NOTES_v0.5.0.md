# dorian v0.5.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

v0.5.0 is a **measurement release**: no functional code changes since
v0.4.0. It publishes the multi-document churn battery that stress-tests
anchor-first extraction beyond the short demo doc.

## What's new since v0.4.0

- **`docs/CHURN_BENCHMARK_v0.5.0.md`** — anchor vs restate churn across four
  committed public documents (34–152 lines, structured prose to
  numbers-dense report), 8 isolated benchmark cells, 5 runs / 10 pairwise
  distances each, every number recomputed from raw artifacts (8/8 valid).
- Headline findings, stated plainly:
  - the anchor advantage holds on **every** document (2–8× lower churn than
    restate), but selection jitter grows with document length;
  - anchor clears the 0.20 advisory gate only on the 34- and 60-line
    documents; at 121+ lines it measures 0.29–0.37 (restate: 0/4 passes,
    0.32–0.78);
  - 3-run churn invocations (v0.3.0/v0.4.0 protocol) underestimate churn
    versus the 10-pair estimator — the earlier numbers were real but
    optimistic; use `--runs 5` or more;
  - anchor's residual churn on long documents is partly off-by-a-line
    boundary jitter (fuzzy ≪ exact), pointing at deterministic boundary
    snapping and consensus span-voting as the next stabilization targets.
- Consequence: **`--extract` remains experimental and draft-only in both
  modes.** The promotion criterion is now sharper: gate-passing churn on
  documents of realistic length.

## How to try it

```bash
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'

# reproduce the battery shape on your own documents:
dorian bench churn --doc your-doc.md --runs 5 --mode anchor
dorian bench churn --doc your-doc.md --runs 5 --mode restate
```

## Unchanged

The full local loop, checker families, trust-state folding, audit export,
downstream recall, content-free sidecars, scope lint, and the GitHub Action
(trusted/internal repositories recommended — see `action/README.md`). All
standing caveats apply, including: the headline benchmark result (32.40× /
0.89 recall) is a research-preview figure on private repositories, not
independent public proof.

## Next steps

- Selection stabilization for anchor mode: deterministic boundary snapping,
  checkability prefilter, consensus-of-k span voting
  (`docs/NEXT_ALGORITHMIC_BETS.md`).
- Level 1 of `docs/SOLO_VALIDATION_LADDER.md`: the reproducible public
  micro-benchmark (requires manual ground-truth labels by design).
- First PyPI release of `dorian-vwp`.
