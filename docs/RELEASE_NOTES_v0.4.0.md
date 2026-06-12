# dorian v0.4.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

v0.4.0 ships the first functional change since v0.1.0: **anchor-first claim
extraction**, the measured answer to the extraction-churn instability
published in v0.3.0.

## What's new since v0.3.0

- **`--extract-mode anchor`** (on `dorian seal --extract` and
  `dorian bench churn --mode anchor`): the model only selects 1-based line
  spans via a forced `emit_spans` tool call; claim text, anchor quote, and id
  (`cL<start>-<end>`) are then derived from the artifact deterministically.
  The model never authors identity-bearing text. Anchors are exact artifact
  substrings by construction. The default mode (`restate`) is unchanged, and
  the two modes hash to different extraction protocols and never share cache
  entries.
- **Measured result** (`docs/CHURN_BENCHMARK_v0.4.0.md`, same 7-agent
  protocol as the v0.3.0 baseline, same doc/model): exact churn mean drops
  from 0.187 to **0.029** (median 0.000), the advisory gate goes from 3/7 to
  **7/7 PASS**, and 4 of 7 invocations produced identical claim sets (by
  normalized claim text) across all 3 re-runs — 15/21 identical run pairs vs
  3/21 for restate. Residual churn is a single borderline span flickering in
  or out.
- Trade-offs, stated plainly: anchor claims are line-grained (~9 per doc vs
  ~17 restated sub-claims), and because the drafted claim text is derived
  from artifact lines, an unedited anchor draft sealed with `--no-quotes`
  still embeds artifact content in the claim text — reword during
  claims.json review when content-free sidecars matter. Both modes remain
  **experimental and draft-only** — anchor mode is measured progress toward
  lifting that status, not the lifting itself. Evidence so far covers one
  short public document.
- `dorian bench churn` records the measured `mode` in its result JSON.
- Version, badge, and pin examples updated to the 0.4 series.

## How to try it

```bash
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'

# draft claims by span selection instead of model wording:
dorian seal docs/design.md --readset rs.json --extract --extract-mode anchor
# then review claims.json and re-seal with --claims, as always

# measure the difference on your own documents:
dorian bench churn --doc your-doc.md --mode anchor
dorian bench churn --doc your-doc.md --mode restate
```

## Unchanged

The full local loop (`capture` → `seal` → `revalidate` → `status` /
`report --audit` / `blast`), checker families, trust-state folding, audit
export, downstream recall, content-free sidecars, scope lint, and the GitHub
Action (trusted/internal repositories recommended — see `action/README.md`
security notes). All standing caveats from
`docs/RELEASE_NOTES_v0.2.0.md` apply, including: the headline benchmark
result (32.40× / 0.89 recall) is owner-checked and model-adjudicated, not
independent public proof.

## Next steps

- Anchor-mode churn on longer, messier documents (the current evidence is
  one short structured doc) and a selection-stability gate.
- Level 1 of `docs/SOLO_VALIDATION_LADDER.md`: the reproducible public
  micro-benchmark.
- First PyPI release of `dorian-vwp`.
