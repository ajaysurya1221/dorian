# Multi-document extraction churn — v0.5.0 (anchor vs restate, 4-doc battery)

v0.4.0 measured anchor-first extraction on one short, structured demo
document. This battery answers the obvious follow-up: **does the anchor
advantage survive longer, messier documents?** Short answer: the advantage
holds everywhere (2–8× lower churn than restate), but selection jitter grows
with document length — anchor mode clears the 0.20 advisory gate only on the
two shorter documents. `--extract` stays experimental in both modes.

## Method

Four committed public documents from this repository, increasing in length
and mess, each measured in both modes by an isolated run of
`dorian bench churn` exactly once with `--runs 5` — 5 independent extraction
runs (`claude-sonnet-4-6`, temperature 0, cache disabled) scoring all 10
pairwise normalized-claim-text Jaccard distances. 10 pairs per cell is the
gate-statistics fix recommended in v0.3.0: a 3-run invocation yields only 3
pairs and a noisy estimate. 8 cells × 5 runs = 40 fresh extraction calls;
every reported number was recomputed from the raw `churn.json` artifacts;
8/8 cells valid, none excluded. Document hashes are pinned in the run
manifest; the demo doc is the same bytes measured in v0.3.0/v0.4.0
(sha256 `213409f3…b200a6a`). All four documents were measured at their
v0.4.0-tag bytes; the v0.5.0 release itself edits one of them
(`action/README.md`, a one-line version-pin bump) after measurement, which
does not affect the measured result.

## Results

| document | lines | mode | exact churn | fuzzy churn | claims/run | identical pairs | gate < 0.20 |
|---|---|---|---:|---:|---:|---|---|
| demo doc (design.md) | 34 | restate | 0.3200 | 0.0956 | 17.2 | 1/10 | FAIL |
| | | anchor | **0.0400** | 0.0400 | 9.2 | 6/10 | **PASS** |
| validation ladder | 60 | restate | 0.6699 | 0.3015 | 29.8 | 0/10 | FAIL |
| | | anchor | **0.1555** | 0.1555 | 13.8 | 1/10 | **PASS** |
| action README | 121 | restate | 0.5672 | 0.2794 | 37.8 | 0/10 | FAIL |
| | | anchor | **0.2875** | 0.2027 | 24.0 | 1/10 | FAIL |
| kill report | 152 | restate | 0.7849 | 0.4057 | 52.2 | 0/10 | FAIL |
| | | anchor | **0.3656** | 0.2192 | 49.4 | 1/10 | FAIL |

Anchor-over-restate churn reduction per document: 8.0×, 4.3×, 2.0×, 2.1×.

## Findings

1. **The anchor advantage is universal but shrinking with length.** Anchor
   churns 2–8× less than restate on every document. As documents grow, the
   wording problem anchor solved stays solved, but the model's remaining
   freedom — *which spans matter* — becomes a larger choice space and
   dominates the churn budget.
2. **The gate is length-bound.** Anchor passes the 0.20 advisory gate on the
   34- and 60-line documents, fails at 121+ lines (0.29, 0.37). Restate
   passes nowhere — 0/4 at 10-pair resolution.
3. **3-run invocations underestimated churn.** The demo doc's restate churn
   measures 0.320 at 10 pairs versus a 0.187 mean across the seven 3-pair
   invocations of v0.3.0 (range 0.074–0.290). More pairs give more chances
   to catch divergent runs; the v0.3.0/v0.4.0 numbers are real but
   optimistic estimates from a noisier estimator. (The v0.4.0 anchor result
   replicates here regardless: 0.029 at 3 pairs, 0.040 at 10.)
4. **Anchor's residual churn on long docs is partly boundary jitter.** On
   the two long documents, anchor's fuzzy churn is well below its exact
   churn (0.20 vs 0.29; 0.22 vs 0.37): many "disagreeing" spans are
   off-by-a-line variants of the same claim, forgiven by fuzzy matching. On
   short documents fuzzy equals exact — boundaries are stable, and the
   only churn is whole-span selection.
5. **Implication for the roadmap.** Anchor-first is necessary but not
   sufficient: the next stabilization targets are *selection* (e.g.,
   consensus-of-k span voting; a deterministic checkability prefilter that
   narrows candidate spans before the model chooses) and *boundaries*
   (snap span edges to sentence/list-item starts deterministically). Both
   compose with the anchor architecture; neither requires the model to
   author text.

## Scope and limits

One invocation per cell (10 pairs each, no cross-invocation variance
estimate); four documents from one repository; one model. The battery
measures draft *stability*, not extraction *quality* — a stable extractor
can still select unhelpful spans. Promotion of `--extract` beyond
experimental remains blocked, now by a sharper criterion: gate-passing
churn on documents of realistic length.
