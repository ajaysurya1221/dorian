# dorian v0.0 gate verdict — day 15

**Verdict: GO / KILL / INCONCLUSIVE** (delete two)

## H1 — checkability
- backed_claim_ratio (pooled): ____  (gate: >= 0.40)
- per repo: ____
- per claim kind: ____

## H2 — precision bet (labeled ground truth)
- FP_baseline / FP_dorian: ____  (gate: >= 2.0)
- recall_dorian: ____  (gate: >= 0.85)
- recall_baseline: ____ (expected ~1.0 by construction)
- bootstrap 95% CIs: ____
- per-checker-class breakdown (C1 / C1-relocated / C3 / C5-typed / C5-shell): ____
- heuristic-GT agreement with labels: ____

## Secondary
- ERRORED rate: ____ (must be < 5% of checker runs)
- extraction churn (Jaccard, 3 re-runs): ____ (gate: < 0.20)
- transcript capture coverage: ____ (gate: >= 0.75)
- C2-lite activated at day-10 checkpoint: yes/no — effect: ____

## Kill criteria triggered (if any)
1. H1 < 0.40: ____
2. H2 fails after C2-lite contingency: ____
3. extraction churn >= 0.20 after hardening: ____
4. capture coverage < 0.75 or overhead > 5%: ____
5. prior-art discovery (W1.2 memo): ____
6. labeled GT pairs < 50 → INCONCLUSIVE: ____

## Decision rationale

____

## If KILL: negative-result publication checklist
- [ ] benchmark harness + data published
- [ ] README front-page admission
- [ ] write-up of where precision actually came from / failed to come from
